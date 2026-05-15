"""Typed accessors for ``agent_registry.yml`` entries (v0.4 schema + app block).

Contract: ../../../docs/contracts/agent-registry-app-block-v0_1.md

agent-compile reads only: ``name``, ``share_class.org``, ``local_user``,
``cert``, ``host``, and the ``app`` block. Everything else in an entry
belongs to rbac-compile / sync-compile / Ansible apply and is ignored here.

This module is a leaf: pure dict access, no config, no I/O. Host resolution
(which needs org_routing) lives in ``paths.resolve_agent_host``.
"""

from __future__ import annotations

from typing import Any, Dict


class AgentEntryError(Exception):
    """Raised when an agent registry entry is missing a field agent-compile needs."""


def _name(agent: Dict[str, Any]) -> str:
    return str(agent.get("name", "<unnamed>"))


def agent_org(agent: Dict[str, Any]) -> str:
    """The agent's home org — ``share_class.org`` in the v0.4 schema."""
    share_class = agent.get("share_class") or {}
    org = share_class.get("org")
    if not org:
        raise AgentEntryError(
            f"agent {_name(agent)!r}: share_class.org is required"
        )
    return str(org)


def app_block(agent: Dict[str, Any]) -> Dict[str, Any]:
    """The ``app`` block. Raises if absent — agent-compile cannot compile without it."""
    app = agent.get("app")
    if not isinstance(app, dict):
        raise AgentEntryError(
            f"agent {_name(agent)!r}: missing 'app' block (template/image/channels). "
            "See the agent-registry-app-block contract."
        )
    return app


def app_template(agent: Dict[str, Any]) -> str:
    app = app_block(agent)
    template = app.get("template")
    if not template:
        raise AgentEntryError(f"agent {_name(agent)!r}: app.template is required")
    return str(template)


def app_image(agent: Dict[str, Any]) -> str:
    app = app_block(agent)
    image = app.get("image")
    if not image:
        raise AgentEntryError(f"agent {_name(agent)!r}: app.image is required")
    return str(image)


def app_channels(agent: Dict[str, Any]) -> Dict[str, Any]:
    """Per-channel instance identity. Empty dict if absent."""
    app = agent.get("app") or {}
    return app.get("channels") or {}


def cert_issue(agent: Dict[str, Any]) -> bool:
    """Whether to emit a dprox cert-request. Defaults to True."""
    cert = agent.get("cert") or {}
    return bool(cert.get("issue", True))


def cert_validity_days(agent: Dict[str, Any], default: int = 365) -> int:
    cert = agent.get("cert") or {}
    return int(cert.get("validity_days", default))
