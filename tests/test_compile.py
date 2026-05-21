"""Tests for the instance compile pipeline."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
import yaml

from agent_compile import compile as compile_mod
from agent_compile import matrix as matrix_mod


AGENT = "agent_arc_marketing_bob"


# --- golden path ------------------------------------------------------------


def test_compile_emits_expected_artifacts(cfg):
    result = compile_mod.compile_agent(cfg, AGENT)
    assert result.flavour == "openclaw"
    assert result.image_version == "2026.5.5-r1"

    root = result.artifact_root
    assert (root / "openclaw.json").is_file()
    assert (root / "secrets.manifest").is_file()
    assert (root / "cert-request.yml").is_file()
    assert (root / "compose.yml").is_file()
    assert (root / "workspace" / "AGENTS.md").is_file()
    assert (root / "workspace" / "SOUL.md").is_file()
    assert (root / "workspace" / "TOOLS.md").is_file()
    assert (root / "workspace" / "skills" / "social_channel_etiquette" / "SKILL.md").is_file()


def test_compile_compose_yml_contents(cfg):
    compile_mod.compile_agent(cfg, AGENT)
    root = cfg.compiled_agent_path(AGENT)
    compose_text = (root / "compose.yml").read_text(encoding="utf-8")
    assert "ghcr.io/jobcpf/openclaw-runtime:2026.5.5-r1" in compose_text
    assert f"openclaw_{AGENT}" in compose_text
    assert f"AGENT_NAME: \"{AGENT}\"" in compose_text
    assert f"/mnt/raid/arc/agents/{AGENT}/configs:/agent/configs:rw" in compose_text
    assert "127.0.0.1:" in compose_text  # port mapping rendered


def test_compile_flavour_json_has_instance_overrides(cfg):
    compile_mod.compile_agent(cfg, AGENT)
    root = cfg.compiled_agent_path(AGENT)
    fj = json.loads((root / "openclaw.json").read_text(encoding="utf-8"))
    assert fj["agent"]["name"] == AGENT
    assert fj["channels"]["discord"]["bot_name"] == "marketing-bob"
    # dprox endpoint resolved from .compiled/dprox_endpoints.yml block form
    # (endpoints.arc.url) per docs/contracts/dprox-endpoints-file-v0_1.md
    assert fj["dprox"]["endpoint"] == "https://dprox-arc.lan:8443"


def test_compile_dprox_endpoint_bare_string_form(cfg):
    """endpoints.<org> may be a bare URL string, not only a {url: ...} block —
    the reader tolerates both (contract v0.1 compatibility note)."""
    dprox_path = cfg.dprox_endpoints_path()
    dprox_path.write_text(
        'endpoints:\n  arc: "https://bare.dprox.internal:8443"\n', encoding="utf-8"
    )
    compile_mod.compile_agent(cfg, AGENT)
    fj = json.loads(
        (cfg.compiled_agent_path(AGENT) / "openclaw.json").read_text(encoding="utf-8")
    )
    assert fj["dprox"]["endpoint"] == "https://bare.dprox.internal:8443"


def test_compile_no_dprox_block_when_template_lacks_one(cfg):
    """agent-compile must NOT invent a dprox block. If neither the bundle nor
    the template configures dprox, the compiled config has no dprox block —
    even though dprox_endpoints.yml has an entry for the agent's org."""
    from agent_compile import registry as registry_mod

    tpl = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 1)
    tpl.overrides["openclaw_json"].pop("dprox", None)
    registry_mod.save_template(cfg, tpl, allow_overwrite=True)

    compile_mod.compile_agent(cfg, AGENT)
    fj = json.loads(
        (cfg.compiled_agent_path(AGENT) / "openclaw.json").read_text(encoding="utf-8")
    )
    assert "dprox" not in fj


def test_compile_flavour_json_keys_sorted(cfg):
    compile_mod.compile_agent(cfg, AGENT)
    root = cfg.compiled_agent_path(AGENT)
    raw = (root / "openclaw.json").read_text(encoding="utf-8")
    # Reading line-by-line: top-level keys in alphabetical order
    fj = json.loads(raw)
    top_keys = list(fj.keys())
    assert top_keys == sorted(top_keys)
    # Indented two spaces, trailing newline
    assert raw.endswith("\n")
    assert "\n  " in raw


def test_compile_secrets_manifest_contains_resolved_refs(cfg):
    compile_mod.compile_agent(cfg, AGENT)
    root = cfg.compiled_agent_path(AGENT)
    sm = yaml.safe_load((root / "secrets.manifest").read_text(encoding="utf-8"))
    names = [s["name"] for s in sm["secrets"]]
    # v1 template enables discord and adds SOCIAL_API_KEY; resolver baseline also
    # includes DISCORD_BOT_TOKEN and OPENCLAW_GATEWAY_TOKEN as SecretRefs.
    assert "DISCORD_BOT_TOKEN" in names
    assert "OPENCLAW_GATEWAY_TOKEN" in names
    assert "SOCIAL_API_KEY" in names
    assert names == sorted(names)
    for entry in sm["secrets"]:
        assert entry["vault_path"] == f"agents/{AGENT}/{entry['name']}"
        assert entry["required"] is True


def test_compile_skill_bodies_copied_verbatim(cfg):
    compile_mod.compile_agent(cfg, AGENT)
    src = (
        Path(cfg.registry_root) / "skills" / "social_channel_etiquette" / "SKILL.md"
    ).read_text(encoding="utf-8")
    dest = (
        cfg.compiled_agent_path(AGENT)
        / "workspace" / "skills" / "social_channel_etiquette" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert src == dest


def test_compile_cert_request_shape(cfg):
    compile_mod.compile_agent(cfg, AGENT)
    root = cfg.compiled_agent_path(AGENT)
    cr = yaml.safe_load((root / "cert-request.yml").read_text(encoding="utf-8"))
    assert cr["cn"] == AGENT
    assert f"openclaw_{AGENT}" in cr["sans"]
    assert cr["key_type"] == "ed25519"
    assert cr["purpose"] == "client_auth"


# --- idempotency ------------------------------------------------------------


def test_compile_byte_identical_rerun(cfg):
    compile_mod.compile_agent(cfg, AGENT)
    root = cfg.compiled_agent_path(AGENT)

    first = {}
    for p in root.rglob("*"):
        if p.is_file():
            first[str(p.relative_to(root))] = p.read_bytes()

    compile_mod.compile_agent(cfg, AGENT)

    second = {}
    for p in root.rglob("*"):
        if p.is_file():
            second[str(p.relative_to(root))] = p.read_bytes()

    assert first == second


# --- failure modes ----------------------------------------------------------


def test_compile_missing_agent(cfg):
    from agent_compile import registry as registry_mod

    with pytest.raises(registry_mod.RegistryError, match="not found"):
        compile_mod.compile_agent(cfg, "agent_does_not_exist")


def test_compile_flavour_mismatch(cfg):
    """An agent whose app.image and app.template flavours disagree fails fast."""
    reg_path = cfg.agent_registry_path()
    reg = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    for agent in reg["agents"]:
        if agent["name"] == AGENT:
            agent["app"]["image"] = "nanoclaw:1.2.3-r1"
    reg_path.write_text(yaml.safe_dump(reg, sort_keys=False), encoding="utf-8")

    with pytest.raises(compile_mod.FlavourMismatchError):
        compile_mod.compile_agent(cfg, AGENT)


def test_compile_broken_matrix_refuses(cfg):
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            flavour="openclaw",
            image="2026.5.5-r1",
            template="marketing_arc:v1",
            status="broken",
            tested_at=matrix_mod.now_iso(),
            notes="poisoned for test",
        ),
    )
    with pytest.raises(compile_mod.MatrixBrokenError):
        compile_mod.compile_agent(cfg, AGENT)


def test_compile_experimental_matrix_warns(cfg):
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            flavour="openclaw",
            image="2026.5.5-r1",
            template="marketing_arc:v1",
            status="experimental",
            tested_at=matrix_mod.now_iso(),
        ),
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        compile_mod.compile_agent(cfg, AGENT)
    assert any(
        isinstance(item.message, compile_mod.MatrixExperimentalWarning) for item in w
    )


def test_compile_experimental_with_allow_flag_does_not_warn(cfg):
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            flavour="openclaw",
            image="2026.5.5-r1",
            template="marketing_arc:v1",
            status="experimental",
            tested_at=matrix_mod.now_iso(),
        ),
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    assert not any(
        isinstance(item.message, compile_mod.MatrixExperimentalWarning) for item in w
    )


def test_compile_missing_skill_body_fails(cfg):
    """Removing a skill from the library after the template references it errors out."""
    skill_path = (
        Path(cfg.registry_root) / "skills" / "social_channel_etiquette" / "SKILL.md"
    )
    skill_path.unlink()
    with pytest.raises(compile_mod.CompileError, match="skill body not found"):
        compile_mod.compile_agent(cfg, AGENT)
