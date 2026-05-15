"""Tests for agent_entry accessors, host resolution, and registry-fixture fidelity.

Contract: docs/contracts/agent-registry-app-block-v0_1.md

The fixture agent_registry.yml mirrors the live ~/ansible/registry/agent_registry.yml
v0.4 schema. These tests fail loudly if the fixture (and so the schema agent-compile
is built against) drifts from that shape.
"""

from __future__ import annotations

import pytest

from agent_compile import agent_entry
from agent_compile import paths as paths_mod
from agent_compile import registry as registry_mod


# --- agent_entry accessors --------------------------------------------------


def test_app_accessors(cfg):
    agent = registry_mod.get_agent(cfg, "agent_arc_marketing_bob")
    assert agent_entry.app_template(agent) == "openclaw:marketing_arc:v1"
    assert agent_entry.app_image(agent) == "openclaw:2026.5.5-r1"
    assert agent_entry.app_channels(agent)["discord"]["bot_name"] == "marketing-bob"


def test_agent_org_from_share_class(cfg):
    agent = registry_mod.get_agent(cfg, "agent_arc_marketing_bob")
    assert agent_entry.agent_org(agent) == "arc"


def test_cert_accessors(cfg):
    agent = registry_mod.get_agent(cfg, "agent_arc_marketing_bob")
    assert agent_entry.cert_issue(agent) is True
    assert agent_entry.cert_validity_days(agent) == 365


def test_app_block_missing_raises():
    """An agent with no `app` block (e.g. the live registry's rbac-only agents)
    cannot be compiled by agent-compile."""
    agent = {"name": "agent_no_app", "share_class": {"org": "arc"}}
    with pytest.raises(agent_entry.AgentEntryError, match="app"):
        agent_entry.app_template(agent)


def test_agent_org_missing_raises():
    agent = {"name": "agent_no_sc"}
    with pytest.raises(agent_entry.AgentEntryError, match="share_class.org"):
        agent_entry.agent_org(agent)


def test_cert_defaults_when_absent():
    agent = {"name": "x"}
    assert agent_entry.cert_issue(agent) is True
    assert agent_entry.cert_validity_days(agent) == 365


# --- host resolution (routing migration) ------------------------------------


def test_host_resolves_via_org_routing_when_absent(cfg):
    """agent_arc_marketing_bob omits `host`; it must resolve to arc's vector_host."""
    agent = registry_mod.get_agent(cfg, "agent_arc_marketing_bob")
    assert "host" not in agent
    assert paths_mod.resolve_agent_host(cfg, agent) == "otter"


def test_explicit_host_wins_over_org_routing(cfg):
    agent = registry_mod.get_agent(cfg, "agent_arc_marketing_bob")
    agent = {**agent, "host": "marten"}
    assert paths_mod.resolve_agent_host(cfg, agent) == "marten"


def test_host_resolution_fails_without_routing_or_host(cfg, tmp_path):
    """No explicit host and no org_routing entry → clear error, never a guess."""
    agent = {"name": "agent_x", "share_class": {"org": "nonexistent_org"}}
    with pytest.raises(paths_mod.HostResolutionError):
        paths_mod.resolve_agent_host(cfg, agent)


def test_agent_host_root_uses_share_class_org(cfg):
    agent = registry_mod.get_agent(cfg, "agent_arc_marketing_bob")
    assert (
        paths_mod.agent_host_root(agent)
        == "/mnt/raid/arc/agents/agent_arc_marketing_bob"
    )


def test_load_org_routing(cfg):
    routing = registry_mod.load_org_routing(cfg)
    assert routing["arc"]["vector_host"] == "otter"
    assert routing["cpf"]["fileserver"] == "beaver"


# --- registry-fixture schema fidelity ---------------------------------------


def test_fixture_reference_agents_match_live_v0_4_shape(cfg):
    """The first four fixture agents are copied verbatim from the live registry.

    They use the v0.4 rbac/sync schema: share_class + local_user + cert, and
    NO `app` block. If this drifts, the fixture no longer mirrors production.
    """
    reg = registry_mod.load_agent_registry(cfg)
    by_name = {a["name"]: a for a in reg["agents"]}
    for name in (
        "agent_oversight",
        "agent_arc_exec",
        "agent_arc_finance_global",
        "agent_platform_test",
    ):
        agent = by_name[name]
        assert "share_class" in agent and "org" in agent["share_class"]
        assert "local_user" in agent
        assert "app" not in agent, (
            f"{name} is a verbatim live-registry reference agent — it must not "
            "carry an app block"
        )


def test_fixture_test_agent_carries_app_block(cfg):
    """agent_arc_marketing_bob is the agent-compile test agent — it must carry
    a full app block per the app-block contract."""
    agent = registry_mod.get_agent(cfg, "agent_arc_marketing_bob")
    assert set(agent["app"]) >= {"template", "image"}
    assert "share_class" in agent
    assert "host" not in agent  # exercises org_routing default
