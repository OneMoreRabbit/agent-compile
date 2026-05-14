"""Shared path helpers for compose.yml and snapshot."""

from __future__ import annotations

from typing import Any, Dict


def agent_host_root(agent: Dict[str, Any]) -> str:
    """Host-side root path for an agent's four-surface tree.

    Org-bounded agents: ``/mnt/raid/<org>/agents/<name>``.
    Top-level agents (``org`` is None / empty): ``/mnt/raid/agents/<name>``.
    """
    name = agent["name"]
    org = agent.get("org")
    if org is None or org == "":
        return f"/mnt/raid/agents/{name}"
    return f"/mnt/raid/{org}/agents/{name}"
