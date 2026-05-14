"""Tests for the SecretRef walker and manifest derivation."""

from __future__ import annotations

from agent_compile import secrets


def test_walk_finds_top_level_secretref():
    json = {"token": {"source": "env", "id": "DISCORD_BOT_TOKEN"}}
    assert secrets.collect_names(json, []) == ["DISCORD_BOT_TOKEN"]


def test_walk_finds_deeply_nested_secretref():
    json = {
        "channels": {
            "discord": {
                "token": {"source": "env", "id": "DISCORD_BOT_TOKEN"}
            }
        }
    }
    assert secrets.collect_names(json, []) == ["DISCORD_BOT_TOKEN"]


def test_walk_finds_multiple_refs_sorted_and_unique():
    json = {
        "discord": {"token": {"source": "env", "id": "DISCORD_BOT_TOKEN"}},
        "anthropic": {"key": {"source": "env", "id": "ANTHROPIC_API_KEY"}},
        "gateway": {"token": {"source": "env", "id": "OPENCLAW_GATEWAY_TOKEN"}},
        "dup": {"token": {"source": "env", "id": "DISCORD_BOT_TOKEN"}},
    }
    names = secrets.collect_names(json, [])
    assert names == ["ANTHROPIC_API_KEY", "DISCORD_BOT_TOKEN", "OPENCLAW_GATEWAY_TOKEN"]


def test_walk_ignores_non_secretref_dicts():
    json = {
        "models": {"auth": {}},
        "agent": {"name": "bob"},
        "channels": {"discord": {"enabled": True}},
    }
    assert secrets.collect_names(json, []) == []


def test_walk_ignores_source_not_env():
    json = {"token": {"source": "vault", "id": "DISCORD_BOT_TOKEN"}}
    assert secrets.collect_names(json, []) == []


def test_walk_finds_refs_inside_lists():
    json = {"tokens": [{"source": "env", "id": "TOK_A"}, {"source": "env", "id": "TOK_B"}]}
    assert secrets.collect_names(json, []) == ["TOK_A", "TOK_B"]


def test_template_manifest_unioned():
    json = {"token": {"source": "env", "id": "ANTHROPIC_API_KEY"}}
    names = secrets.collect_names(json, ["SOCIAL_API_KEY", "ANTHROPIC_API_KEY"])
    assert names == ["ANTHROPIC_API_KEY", "SOCIAL_API_KEY"]


def test_derive_secret_manifest_shape():
    json = {"token": {"source": "env", "id": "DISCORD_BOT_TOKEN"}}
    manifest = secrets.derive_secret_manifest(json, [], agent_name="agent_a")
    assert manifest == [
        {
            "name": "DISCORD_BOT_TOKEN",
            "vault_path": "agents/agent_a/DISCORD_BOT_TOKEN",
            "required": True,
        }
    ]
