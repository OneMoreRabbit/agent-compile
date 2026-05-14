"""Tests for the identifier parser/formatter.

Contract: docs/contracts/identifier-format-v0_1.md
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
