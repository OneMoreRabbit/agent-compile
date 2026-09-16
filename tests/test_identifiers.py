"""Tests for the identifier parser/formatter.

Contract: .atlas/components/agent-compile/docs/provides/ (identifier-format)
"""

from __future__ import annotations

import pytest

from agent_compile.identifiers import (
    IdentifierError,
    ImageDefaultsRef,
    ImageRef,
    TemplateID,
    parse,
    parse_image_defaults_ref,
    parse_image_ref,
    parse_template_id,
)


# --- TemplateID -------------------------------------------------------------


def test_template_id_roundtrip():
    tid = parse("openclaw:marketing_arc:v3")
    assert isinstance(tid, TemplateID)
    assert tid.flavour == "openclaw"
    assert tid.name == "marketing_arc"
    assert tid.version == 3
    assert str(tid) == "openclaw:marketing_arc:v3"


def test_template_id_v1():
    tid = parse("nanoclaw:light_assistant:v1")
    assert tid == TemplateID("nanoclaw", "light_assistant", 1)


@pytest.mark.parametrize(
    "bad",
    [
        "openclaw:marketing_arc:v0",        # v0 reserved
        "openclaw:marketing_arc:3",         # missing v
        "openclaw:marketing_arc:vthree",    # not numeric
        "openclaw:image_defaults:v1",       # reserved name
        "Openclaw:marketing_arc:v1",        # uppercase flavour
        "openclaw:Marketing:v1",            # uppercase name
        "openclaw:marketing-arc:v1",        # hyphen in name
        "openclaw::v1",                     # empty name
        ":marketing_arc:v1",                # empty flavour
        "",
        "openclaw:marketing_arc:v1:extra",  # too many fields
        "single",                           # too few fields
    ],
)
def test_template_id_rejects_bad(bad):
    with pytest.raises(IdentifierError):
        parse(bad)


# --- ImageDefaultsRef -------------------------------------------------------


def test_image_defaults_ref_roundtrip():
    ref = parse("image_defaults:openclaw:2026.5.5-r1")
    assert isinstance(ref, ImageDefaultsRef)
    assert ref.flavour == "openclaw"
    assert ref.image_version == "2026.5.5-r1"
    assert str(ref) == "image_defaults:openclaw:2026.5.5-r1"


def test_image_defaults_ref_nanoclaw():
    ref = parse("image_defaults:nanoclaw:1.2.3-r1")
    assert ref == ImageDefaultsRef("nanoclaw", "1.2.3-r1")


@pytest.mark.parametrize(
    "bad",
    [
        "image_defaults:openclaw:2026.5.5",       # no -r<rev>
        "image_defaults:openclaw:2026.5.5-r0",    # r0 invalid
        "image_defaults:openclaw:2026.5.5-rX",    # non-numeric rev
        "image_defaults:Openclaw:2026.5.5-r1",    # uppercase flavour
    ],
)
def test_image_defaults_ref_rejects_bad(bad):
    with pytest.raises(IdentifierError):
        parse(bad)


# --- ImageRef ---------------------------------------------------------------


def test_image_ref_roundtrip():
    ref = parse("openclaw:2026.5.5-r1")
    assert isinstance(ref, ImageRef)
    assert ref.flavour == "openclaw"
    assert ref.image_version == "2026.5.5-r1"
    assert str(ref) == "openclaw:2026.5.5-r1"


def test_image_ref_higher_rev():
    ref = parse("openclaw:2026.7.2-r3")
    assert ref == ImageRef("openclaw", "2026.7.2-r3")


# --- Typed parse helpers ----------------------------------------------------


def test_parse_template_id_rejects_other_shapes():
    with pytest.raises(IdentifierError):
        parse_template_id("image_defaults:openclaw:2026.5.5-r1")
    with pytest.raises(IdentifierError):
        parse_template_id("openclaw:2026.5.5-r1")


def test_parse_image_ref_rejects_other_shapes():
    with pytest.raises(IdentifierError):
        parse_image_ref("openclaw:marketing_arc:v1")
    with pytest.raises(IdentifierError):
        parse_image_ref("image_defaults:openclaw:2026.5.5-r1")


def test_parse_image_defaults_ref_rejects_other_shapes():
    with pytest.raises(IdentifierError):
        parse_image_defaults_ref("openclaw:marketing_arc:v1")
    with pytest.raises(IdentifierError):
        parse_image_defaults_ref("openclaw:2026.5.5-r1")


# --- Disambiguation rules ---------------------------------------------------


def test_image_defaults_prefix_always_treated_as_defaults_ref():
    """Three-field identifier starting with `image_defaults` is always a defaults ref."""
    ref = parse("image_defaults:openclaw:2026.5.5-r1")
    assert not isinstance(ref, TemplateID)
    assert isinstance(ref, ImageDefaultsRef)


def test_two_field_always_image_ref():
    """A two-field identifier is always an image ref, never a partial template ID."""
    ref = parse("openclaw:2026.5.5-r1")
    assert isinstance(ref, ImageRef)


# --- rev widening (identifier-format 0.4) -----------------------------------
#
# The estate builds and blesses dotted revs — r8.1 is a patch of r8 — and 0.3's
# "r + positive integer" refused images that already existed and were
# pull-verified. Renaming them would have forged an identity.

@pytest.mark.parametrize(
    "image_version",
    ["2026.5.5-r1", "2026.6.35-r8.1", "2026.6.11-r8.1", "2026.6.35-r8.1.2",
     "2026.6.35-r8.0"],
)
def test_dotted_revs_are_accepted(image_version):
    ref = parse_image_ref(f"openclaw:{image_version}")
    assert ref.image_version == image_version


@pytest.mark.parametrize(
    "bad",
    ["2026.5.5-r0",     # rev starts at 1
     "2026.5.5-r",      # no rev
     "2026.5.5-r1.",    # trailing dot
     "2026.5.5-r.1",    # leading dot
     "2026.5.5-r01",    # leading zero
     "2026.5.5-r8.01",  # leading zero in a later component
     "2026.5.5-r8..1"], # empty component
)
def test_malformed_revs_are_still_rejected(bad):
    with pytest.raises(IdentifierError):
        parse_image_ref(f"openclaw:{bad}")


def test_a_dotted_rev_still_derives_the_schema_dir():
    """`rsplit('-r', 1)` must not be confused by dots inside the rev.

    The schema dir comes from stripping the rev; a dotted rev that split wrongly
    would send the compose template lookup to a directory that does not exist.
    """
    from agent_compile import config as config_mod

    cfg = config_mod.load()
    assert cfg.flavour_templates_dir("openclaw", "2026.6.35-r8.1").name == "v2026.6.35"
    assert cfg.image_defaults_path("openclaw", "2026.6.35-r8.1").name == "2026.6.35-r8.1"
