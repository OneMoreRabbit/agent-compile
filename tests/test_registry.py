"""Tests for registry I/O — image_defaults bundle, templates, agent registry."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from agent_compile import config as config_mod
from agent_compile import registry as registry_mod


# --- image_defaults bundle --------------------------------------------------


def test_load_image_defaults(cfg):
    bundle = registry_mod.load_image_defaults(cfg, "openclaw", "2026.5.5-r1")
    assert bundle.flavour == "openclaw"
    assert bundle.image_version == "2026.5.5-r1"
    assert "gateway" in bundle.flavour_json
    assert "AGENTS.md" in bundle.workspace
    assert "SOUL.md" in bundle.workspace
    assert "TOOLS.md" in bundle.workspace
    assert bundle.metadata["image_version"] == "2026.5.5-r1"
    assert bundle.probe_report is not None


def test_load_image_defaults_missing_bundle(cfg):
    with pytest.raises(registry_mod.RegistryError, match="not found"):
        registry_mod.load_image_defaults(cfg, "openclaw", "9999.0.0-r1")


def test_load_image_defaults_unknown_flavour(cfg):
    with pytest.raises(registry_mod.RegistryError, match="flavour"):
        registry_mod.load_image_defaults(cfg, "bogusflavour", "2026.5.5-r1")


def test_load_image_defaults_missing_required_file(tmp_path: Path):
    """Removing a required workspace file makes loading fail."""
    bundle_dir = tmp_path / "registry" / "image_defaults" / "openclaw" / "2026.5.5-r1"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "openclaw.json").write_text("{}")
    (bundle_dir / "workspace").mkdir()
    (bundle_dir / "workspace" / "AGENTS.md").write_text("a")
    # SOUL.md missing on purpose
    (bundle_dir / "workspace" / "TOOLS.md").write_text("t")
    (bundle_dir / "metadata.yml").write_text("image_version: 2026.5.5-r1\n")

    cfg = config_mod.load(registry_root_override=tmp_path / "registry")
    with pytest.raises(registry_mod.RegistryError, match="SOUL.md"):
        registry_mod.load_image_defaults(cfg, "openclaw", "2026.5.5-r1")


def test_load_image_defaults_warns_on_unknown_file(cfg):
    bundle_dir = cfg.image_defaults_path("openclaw", "2026.5.5-r1")
    (bundle_dir / "future_extension.yml").write_text("hello: world\n")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        registry_mod.load_image_defaults(cfg, "openclaw", "2026.5.5-r1")
    messages = [str(item.message) for item in w]
    assert any("future_extension.yml" in m for m in messages)


# --- templates --------------------------------------------------------------


def test_load_template(cfg):
    tpl = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 1)
    assert tpl.flavour == "openclaw"
    assert tpl.name == "marketing_arc"
    assert tpl.version == 1
    assert tpl.parent == "image_defaults:openclaw:2026.5.5-r1"
    assert tpl.id == "openclaw:marketing_arc:v1"
    assert tpl.overrides["openclaw_json"]["channels"]["discord"]["enabled"] is True
    assert "SOUL.md" in tpl.overrides["workspace"]
    assert "social_channel_etiquette" in tpl.overrides["skills"]["add"]
    assert tpl.secret_manifest == ["SOCIAL_API_KEY"]
    assert tpl.preferred_image == "openclaw:2026.5.5-r1"


def test_template_exists(cfg):
    assert registry_mod.template_exists(cfg, "openclaw", "marketing_arc", 1)
    assert not registry_mod.template_exists(cfg, "openclaw", "marketing_arc", 99)


def test_list_templates(cfg):
    out = registry_mod.list_templates(cfg)
    assert "openclaw" in out
    assert "marketing_arc" in out["openclaw"]
    assert out["openclaw"]["marketing_arc"] == [1, 2]


def test_list_templates_filter(cfg):
    out = registry_mod.list_templates(cfg, flavour="openclaw")
    assert set(out.keys()) == {"openclaw"}


def test_save_template_atomic(cfg):
    """Save a new template version, then read it back."""
    new = registry_mod.Template(
        flavour="openclaw",
        name="marketing_arc",
        version=3,
        parent="openclaw:marketing_arc:v2",
        description="v3 — added a tweak",
        derived_from={"kind": "fork", "source": "openclaw:marketing_arc:v2", "at": "2026-05-14T12:00:00Z"},
        overrides={
            "openclaw_json": {"channels": {"discord": {"allowFrom": ["partner-org"]}}},
            "workspace": {},
            "skills": {},
        },
        secret_manifest=[],
        preferred_image="openclaw:2026.5.5-r1",
    )
    path = registry_mod.save_template(cfg, new)
    assert path.is_file()
    reloaded = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 3)
    assert reloaded.parent == "openclaw:marketing_arc:v2"
    assert reloaded.overrides["openclaw_json"]["channels"]["discord"]["allowFrom"] == ["partner-org"]


def test_save_template_refuses_overwrite(cfg):
    existing = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 1)
    with pytest.raises(registry_mod.RegistryError, match="already exists"):
        registry_mod.save_template(cfg, existing)


def test_load_template_flavour_mismatch_rejects(cfg):
    """A template file whose `flavour:` field doesn't match the directory is rejected."""
    path = cfg.template_path("openclaw", "marketing_arc", 1)
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents.replace("flavour: openclaw", "flavour: nanoclaw"), encoding="utf-8")
    with pytest.raises(registry_mod.RegistryError, match="flavour"):
        registry_mod.load_template(cfg, "openclaw", "marketing_arc", 1)


# --- agent registry ---------------------------------------------------------


def test_load_agent_registry(cfg):
    reg = registry_mod.load_agent_registry(cfg)
    names = [a["name"] for a in reg["agents"]]
    assert "agent_arc_marketing_bob" in names


def test_get_agent(cfg):
    agent = registry_mod.get_agent(cfg, "agent_arc_marketing_bob")
    assert agent["app"]["template"] == "openclaw:marketing_arc:v1"
    assert agent["app"]["image"] == "openclaw:2026.5.5-r1"
    assert agent["share_class"]["org"] == "arc"


def test_get_agent_missing(cfg):
    with pytest.raises(registry_mod.RegistryError, match="not found"):
        registry_mod.get_agent(cfg, "agent_does_not_exist")
