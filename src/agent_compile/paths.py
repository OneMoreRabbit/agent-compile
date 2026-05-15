"""Shared path + host helpers for compose.yml, snapshot, and compile.

Host resolution implements the routing-migration contract: ``host`` is
optional in agent_registry.yml v0.4 and defaults to the agent's org's
appserver — ``org_routing[<share_class.org>].vector_host``.
"""

from __future__ import annotations

from typing import Any, Dict

from . import agent_entry
from . import registry as registry_mod
from .config import Config


class HostResolutionError(Exception):
    pass


def agent_host_root(agent: Dict[str, Any]) -> str:
    """Host-side root path for an agent's four-surface tree.

    Org-bounded agents: ``/mnt/raid/<org>/agents/<name>``.
    Top-level agents (``share_class.org == 'top'``) follow the same shape —
    ``top`` is a regular org in the v0.4 routing model.
    """
    name = agent["name"]
    org = agent_entry.agent_org(agent)
    return f"/mnt/raid/{org}/agents/{name}"


def resolve_agent_host(cfg: Config, agent: Dict[str, Any]) -> str:
    """Resolve the appserver host for an agent.

    Explicit ``host`` in the registry entry wins. Otherwise default to the
    agent org's ``vector_host`` from org_routing. Raises if neither is
    available — agent-compile never guesses a host.
    """
    explicit = agent.get("host")
    if explicit:
        return str(explicit)

    org = agent_entry.agent_org(agent)
    routing = registry_mod.load_org_routing(cfg)
    if not routing:
        raise HostResolutionError(
            f"agent {agent.get('name')!r}: no 'host' set and org_routing not "
            f"found at {cfg.org_routing_path()} — set host explicitly or "
            "point config.paths.org_routing_file at the routing table"
        )
    org_entry = routing.get(org)
    if not org_entry or not org_entry.get("vector_host"):
        raise HostResolutionError(
            f"agent {agent.get('name')!r}: no 'host' set and org_routing has "
            f"no vector_host for org {org!r}"
        )
    return str(org_entry["vector_host"])
