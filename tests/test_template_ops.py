"""Tests for ``template_ops`` — new and fork."""

from __future__ import annotations

import pytest

from agent_compile import identifiers
from agent_compile import registry as registry_mod
from agent_compile import template_ops


# --- new --------------------------------------------------------------------


def test_new_template_creates_v1(cfg):
    new_id = identifiers.TemplateID("openclaw", "hr_global", 1)
    img = identifiers.ImageDefaultsRef("openclaw", "2026.5.5-r1")
    path = template_ops.new_template(cfg, new_id, img, description="HR baseline")
    assert path.is_file()

    tpl = registry_mod.load_template(cfg, "openclaw", "hr_global", 1)
    assert tpl.parent == "image_defaults:openclaw:2026.5.5-r1"
    assert tpl.description == "HR baseline"
    assert tpl.derived_from["kind"] == "hand_authored"
    assert tpl.overrides["openclaw_json"] == {}
    assert tpl.overrides["workspace"] == {}
    assert tpl.overrides["skills"] == {}
    assert tpl.secret_manifest == []
    assert tpl.preferred_image == "openclaw:2026.5.5-r1"


def test_new_template_rejects_existing(cfg):
    new_id = identifiers.TemplateID("openclaw", "marketing_arc", 1)
    img = identifiers.ImageDefaultsRef("openclaw", "2026.5.5-r1")
    with pytest.raises(template_ops.TemplateOpsError, match="already exists"):
        template_ops.new_template(cfg, new_id, img)


def test_new_template_rejects_missing_bundle(cfg):
    new_id = identifiers.TemplateID("openclaw", "hr_global", 1)
    img = identifiers.ImageDefaultsRef("openclaw", "9999.0.0-r1")
    with pytest.raises(template_ops.TemplateOpsError, match="bundle not found"):
        template_ops.new_template(cfg, new_id, img)


def test_new_template_cross_flavour_rejected(cfg):
    new_id = identifiers.TemplateID("nanoclaw", "hr_global", 1)
    img = identifiers.ImageDefaultsRef("openclaw", "2026.5.5-r1")
    with pytest.raises(template_ops.TemplateOpsError, match="flavour mismatch"):
        template_ops.new_template(cfg, new_id, img)


def test_new_template_rejects_non_v1(cfg):
    new_id = identifiers.TemplateID("openclaw", "hr_global", 2)
    img = identifiers.ImageDefaultsRef("openclaw", "2026.5.5-r1")
    with pytest.raises(template_ops.TemplateOpsError, match="v1"):
        template_ops.new_template(cfg, new_id, img)


# --- fork -------------------------------------------------------------------


def test_fork_template_copies_overrides_and_uses_source_parent(cfg):
    """The fork's parent matches the source's parent, not the source itself."""
    source = identifiers.TemplateID("openclaw", "marketing_arc", 1)
    new = identifiers.TemplateID("openclaw", "marketing_eu", 1)
    template_ops.fork_template(cfg, source, new)

    forked = registry_mod.load_template(cfg, "openclaw", "marketing_eu", 1)
    src = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 1)
    assert forked.parent == src.parent
    assert forked.derived_from["kind"] == "fork"
    assert forked.derived_from["source"] == "openclaw:marketing_arc:v1"
    assert (
        forked.overrides["openclaw_json"]["channels"]["discord"]["enabled"] is True
    )
    assert forked.secret_manifest == src.secret_manifest


def test_fork_template_deep_copies_overrides(cfg):
    """Mutating the forked template's overrides must not affect the source."""
    source = identifiers.TemplateID("openclaw", "marketing_arc", 1)
    new = identifiers.TemplateID("openclaw", "marketing_eu", 1)
    template_ops.fork_template(cfg, source, new)

    forked = registry_mod.load_template(cfg, "openclaw", "marketing_eu", 1)
    forked.overrides["openclaw_json"]["channels"]["discord"]["enabled"] = False
    registry_mod.save_template(cfg, forked, allow_overwrite=True)

    src_again = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 1)
    assert src_again.overrides["openclaw_json"]["channels"]["discord"]["enabled"] is True


def test_fork_template_rejects_existing(cfg):
    source = identifiers.TemplateID("openclaw", "marketing_arc", 1)
    new = identifiers.TemplateID("openclaw", "marketing_arc", 1)  # collides
    with pytest.raises(template_ops.TemplateOpsError, match="already exists"):
        template_ops.fork_template(cfg, source, new)


def test_fork_template_cross_flavour_rejected(cfg):
    source = identifiers.TemplateID("openclaw", "marketing_arc", 1)
    new = identifiers.TemplateID("nanoclaw", "marketing_arc", 1)
    with pytest.raises(template_ops.TemplateOpsError, match="cross-flavour"):
        template_ops.fork_template(cfg, source, new)


def test_fork_template_rejects_non_v1(cfg):
    source = identifiers.TemplateID("openclaw", "marketing_arc", 1)
    new = identifiers.TemplateID("openclaw", "other", 2)
    with pytest.raises(template_ops.TemplateOpsError, match="v1"):
        template_ops.fork_template(cfg, source, new)


def test_fork_template_missing_source_rejected(cfg):
    source = identifiers.TemplateID("openclaw", "does_not_exist", 1)
    new = identifiers.TemplateID("openclaw", "other", 1)
    with pytest.raises(registry_mod.RegistryError, match="not found"):
        template_ops.fork_template(cfg, source, new)


# --- identifier helper ------------------------------------------------------


def test_parse_template_handle():
    assert identifiers.parse_template_handle("openclaw:marketing_arc") == (
        "openclaw",
        "marketing_arc",
    )


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "openclaw",
        "openclaw:marketing_arc:v1",  # three fields
        "openclaw:image_defaults",     # reserved name
        ":marketing_arc",
        "openclaw:",
    ],
)
def test_parse_template_handle_rejects_bad(bad):
    with pytest.raises(identifiers.IdentifierError):
        identifiers.parse_template_handle(bad)
