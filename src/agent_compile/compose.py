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
    template_dir = cfg.flavour_templates_dir(flavour, image_version)
    template_path = template_dir / "compose.yml.j2"
    if not template_path.is_file():
        raise ComposeError(
            f"compose template not found for flavour={flavour}, "
            f"image_version={image_version}: {template_path}"
        )

    host = agent.get("host")
    if not host:
        raise ComposeError(
            f"agent {agent.get('name')!r}: registry entry missing required 'host' field"
        )

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
