"""Compose.yml rendering.

Jinja-renders a per-flavour, per-schema-version ``compose.yml.j2`` with
fields drawn from the agent registry entry, the resolved image_version,
and an allocated local port.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import jinja2
import yaml

from . import paths as paths_mod
from . import port_allocator
from .config import Config


class ComposeError(Exception):
    pass


def render(
    cfg: Config,
    *,
    flavour: str,
    image_version: str,
    agent: Dict[str, Any],
) -> str:
    """Return the rendered compose.yml text.

    Side-effect: persists the agent's port allocation under the flavour's
    endpoints file. Re-rendering the same agent reuses the same port.
    """
    template_dir = _resolve_compose_template_dir(cfg, flavour, image_version)

    try:
        host = paths_mod.resolve_agent_host(cfg, agent)
    except paths_mod.HostResolutionError as e:
        raise ComposeError(str(e)) from e

    allocation = port_allocator.allocate(cfg, flavour, agent["name"], host)

    flav_cfg = cfg.flavour(flavour)
    local_user = agent.get("local_user") or {}
    supp_gids: List[int] = resolve_supp_gids(cfg, agent)

    # StrictUndefined is the control, not a nicety (ADR-0010 §7). jinja2's
    # default Undefined renders as an empty string, so a template still using
    # the retired `host_root` would emit `/configs:/agent/configs` — an
    # absolute path to the host root, plausible and wrong, with no error. A
    # template that missed the rename now fails at render, whether it came
    # from an image-defaults bundle or this repo's fallback tree, so neither
    # side has to trust the other's timing.
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
    )
    tmpl = env.get_template("compose.yml.j2")
    context = {
        "agent_name": agent["name"],
        "ghcr_org": cfg.ghcr_org,
        "image_line": flav_cfg.image_line,
        "image_version": image_version,
        "uid": local_user.get("uid", ""),
        "primary_gid": local_user.get("primary_gid", ""),
        "supp_gids": supp_gids,
        "supp_gids_str": ",".join(str(g) for g in supp_gids),
        # ADR-0010 §7: two declared roots, not one. `host_root` is retired.
        "beaver_root": paths_mod.agent_beaver_root(agent),
        "local_root": paths_mod.agent_local_root(agent),
        "local_port": allocation.local_port,
        "default_port": flav_cfg.default_port,
        "health_endpoint": flav_cfg.health_endpoint,
    }
    return tmpl.render(**context)



def resolve_supp_gids(cfg: Config, agent: Dict[str, Any]) -> List[int]:
    """An agent's supplementary GIDs: names from the plan, numbers from the map.

    ADR-0013 R6. Until now this read ``local_user.supp_gids``, a field that is
    not in the v0.4 registry schema and that nobody populates — so every agent
    compiled with ``AGENT_SUPP_GIDS: ""`` and no ``group_add``. The old
    behaviour was *documented* (app-block v0_7 said "agent-compile defaults it
    to []") and still wrong: a declared default whose consequence nobody traced.

    The join, per the ruled shape:

      compiled_plan.yml  agent_users[] where name == <agent>  -> .groups  (names)
      group_gid_map.yml  name -> gid                                      (numbers)

    A compiler cannot observe numbers (rbac-compile's Q2 ruling: "a
    compiler-emitted number would be a guess with a compiled pedigree"), so the
    numbers come from the assigner's write-on-assign record and this function
    invents none.

    THREE ABSENCES, KEPT DISTINCT — collapsing them is the defect this replaces:

    1. the agent is missing from ``agent_users[]``  -> error
    2. a named group is missing from the map        -> error, naming both
    3. the plan lists no groups for the agent       -> [] , legitimately

    Only (3) may produce an empty list. Empty is now a statement the plan makes,
    never the residue of a key that was never there.
    """
    name = agent.get("name", "")
    plan_path = cfg.compiled_plan_path()
    map_path = cfg.group_gid_map_path()

    if not plan_path.is_file():
        raise ComposeError(
            f"compiled_plan.yml not found at {plan_path} — it is the source of "
            f"{name}'s group names (rbac-compile writes it). Without it the "
            "supplementary group set cannot be resolved, and emitting an empty "
            "one would silently strip the agent's access."
        )
    with plan_path.open(encoding="utf-8") as f:
        plan = yaml.safe_load(f) or {}

    entries = plan.get("agent_users") or []
    match = next((e for e in entries if (e or {}).get("name") == name), None)
    if match is None:
        raise ComposeError(
            f"agent {name!r} has no entry in agent_users[] of {plan_path}. "
            "agent-compile cannot tell 'no groups' from 'not in the plan', and "
            "guessing empty is the defect ADR-0013 R6 removes. Compile the RBAC "
            "plan for this agent first."
        )

    names = list(match.get("groups") or [])
    if not names:
        return []            # (3) — stated by the plan, not inferred

    if not map_path.is_file():
        raise ComposeError(
            f"group_gid_map.yml not found at {map_path}, but the plan gives "
            f"{name} {len(names)} group(s): {', '.join(names)}. The map is "
            "written on assign by ansible-platform; without it these names "
            "cannot be numbered."
        )
    with map_path.open(encoding="utf-8") as f:
        gid_map = yaml.safe_load(f) or {}
    # Tolerate a wrapper key, as the dprox endpoints file does; the map's own
    # contract is pending (ADR-0013 R6) and this is the shape in use.
    if "groups" in gid_map and isinstance(gid_map["groups"], dict):
        gid_map = gid_map["groups"]

    gids: List[int] = []
    missing: List[str] = []
    for g in names:
        if g in gid_map:
            gids.append(int(gid_map[g]))
        else:
            missing.append(g)
    if missing:
        raise ComposeError(
            f"agent {name!r}: the plan names group(s) {', '.join(missing)} with "
            f"no entry in {map_path}. A plan ahead of the map is normal — the map "
            "is written on assign — so this is a sequencing stop, not a bad plan. "
            "Emitting the resolvable subset would attach a partial group set and "
            "report success, which is the failure ADR-0013 R6 exists to remove."
        )
    return gids


def _resolve_compose_template_dir(
    cfg: Config, flavour: str, image_version: str
) -> Path:
    """Locate the directory that holds ``compose.yml.j2``.

    Resolution order:

    1. The **image-defaults bundle** for this image
       (``image_defaults/<flavour>/<image_version>/``). image-compile is
       proposed to ship the compose template there, per release — see
       ``docs/agent-compile-compose-template-in-bundle-proposal-v0_1.md``.
       A bundle that predates that proposal simply has no ``compose.yml.j2``
       and resolution falls through.
    2. agent-compile's own per-schema tree
       (``templates/<flavour>/v<schema>/``) — the fallback, and the current
       home of the template until bundles ship one.
    """
    bundle_dir = cfg.image_defaults_path(flavour, image_version)
    fallback_dir = cfg.flavour_templates_dir(flavour, image_version)
    for candidate in (bundle_dir, fallback_dir):
        if (candidate / "compose.yml.j2").is_file():
            return candidate
    raise ComposeError(
        f"compose.yml.j2 not found for flavour={flavour}, "
        f"image_version={image_version}: looked in the image-defaults "
        f"bundle ({bundle_dir}) then the per-schema fallback ({fallback_dir})"
    )
