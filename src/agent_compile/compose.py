"""Compose.yml rendering.

Jinja-renders a per-flavour, per-schema-version ``compose.yml.j2`` with
fields drawn from the agent registry entry, the resolved image_version,
and an allocated local port.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import jinja2

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
    supp_gids: List[int] = list(local_user.get("supp_gids") or [])

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
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
        "host_root": paths_mod.agent_host_root(agent),
        "local_port": allocation.local_port,
        "default_port": flav_cfg.default_port,
        "health_endpoint": flav_cfg.health_endpoint,
    }
    return tmpl.render(**context)


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
