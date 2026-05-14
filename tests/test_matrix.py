"""Tests for compatibility matrix R/W.

Contract: docs/contracts/compatibility-matrix-entry-schema-v0_1.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_compile import matrix


def _entry(**overrides) -> matrix.MatrixEntry:
    base = dict(
        flavour="openclaw",
        image="2026.5.5-r1",
        template="marketing_arc:v3",
        status="blessed",
        tested_at="2026-05-14T10:00:00Z",
        test_agent="agent_arc_marketing_bob",
        notes="initial",
    )
    base.update(overrides)
    return matrix.MatrixEntry(**base)


def test_load_empty(tmp_path: Path):
    assert matrix.load(tmp_path / "nope.yml") == []


def test_upsert_creates_file(tmp_path: Path):
    path = tmp_path / "compatibility_matrix.yml"
    matrix.upsert(path, _entry())
    entries = matrix.load(path)
    assert len(entries) == 1
    assert entries[0].flavour == "openclaw"
    assert entries[0].template == "marketing_arc:v3"
    assert entries[0].status == "blessed"


def test_upsert_replaces_existing_by_key(tmp_path: Path):
    path = tmp_path / "compatibility_matrix.yml"
    matrix.upsert(path, _entry(status="experimental"))
    matrix.upsert(path, _entry(status="blessed", notes="promoted"))
    entries = matrix.load(path)
    assert len(entries) == 1
    assert entries[0].status == "blessed"
    assert entries[0].notes == "promoted"


def test_upsert_appends_different_key(tmp_path: Path):
    path = tmp_path / "compatibility_matrix.yml"
    matrix.upsert(path, _entry())
    matrix.upsert(path, _entry(template="hr_global:v1"))
    entries = matrix.load(path)
    assert len(entries) == 2
    assert {e.template for e in entries} == {"marketing_arc:v3", "hr_global:v1"}


def test_upsert_different_flavour(tmp_path: Path):
    path = tmp_path / "compatibility_matrix.yml"
    matrix.upsert(path, _entry())
    matrix.upsert(path, _entry(flavour="nanoclaw", image="1.2.3-r1"))
    entries = matrix.load(path)
    assert len(entries) == 2


def test_find(tmp_path: Path):
    path = tmp_path / "compatibility_matrix.yml"
    matrix.upsert(path, _entry())
    matrix.upsert(path, _entry(template="hr_global:v1"))
    entries = matrix.load(path)

    assert matrix.find(entries, "openclaw", "2026.5.5-r1", "marketing_arc:v3") is not None
    assert matrix.find(entries, "openclaw", "2026.5.5-r1", "hr_global:v1") is not None
    assert matrix.find(entries, "openclaw", "2026.5.5-r1", "missing:v1") is None


def test_upsert_invalid_status_raises(tmp_path: Path):
    path = tmp_path / "compatibility_matrix.yml"
    with pytest.raises(matrix.MatrixError):
        matrix.upsert(path, _entry(status="happy"))


def test_image_defaults_self_entry_shape(tmp_path: Path):
    """image-compile writes self-blessed entries with the long-form template field."""
    path = tmp_path / "compatibility_matrix.yml"
    matrix.upsert(
        path,
        matrix.MatrixEntry(
            flavour="openclaw",
            image="2026.5.5-r1",
            template="image_defaults:openclaw:2026.5.5-r1",
            status="blessed",
            tested_at=matrix.now_iso(),
            test_agent="",
            notes="Auto-blessed: image defaults against own image.",
        ),
    )
    entries = matrix.load(path)
    assert entries[0].template == "image_defaults:openclaw:2026.5.5-r1"
    assert entries[0].test_agent == ""


def test_now_iso_parsable():
    s = matrix.now_iso()
    parsed = matrix.parse_iso(s)
    assert parsed.tzinfo is not None
