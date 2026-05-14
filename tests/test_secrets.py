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


def test_walk_matches_three_field_secretref():
    """openclaw v2026.5.5+ requires `provider` alongside `source` and `id`.

    The walker is shape-based — `source == "env"` plus a string `id` — and
    treats any other keys as opaque attributes. This locks the forward-compat
    contract called out in [[agent-compile-alignment-notes-v0_1]].
    """
    json = {
        "token": {
            "source": "env",
            "provider": "default",
            "id": "OPENCLAW_GATEWAY_TOKEN",
        }
    }
    assert secrets.collect_names(json, []) == ["OPENCLAW_GATEWAY_TOKEN"]


def test_walk_matches_secretref_with_unknown_future_keys():
    """Any extra keys beyond source/id/provider are treated as opaque."""
    json = {
        "token": {
            "source": "env",
            "provider": "default",
            "version": 2,
            "rotates_every_days": 30,
            "id": "TOKEN_X",
        }
    }
    assert secrets.collect_names(json, []) == ["TOKEN_X"]


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
