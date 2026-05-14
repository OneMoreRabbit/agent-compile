"""Tests for matrix bless logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_compile import bless as bless_mod
from agent_compile import matrix as matrix_mod


KEY = dict(flavour="openclaw", image="2026.5.5-r1", template="marketing_arc:v1")


def _experimental_entry(tested_at: str = None) -> matrix_mod.MatrixEntry:
    return matrix_mod.MatrixEntry(
        status="experimental",
        tested_at=tested_at or matrix_mod.now_iso(),
        test_agent="",
        notes="",
        **KEY,
    )


def test_bless_promotes_experimental_to_blessed(cfg):
    matrix_mod.upsert(cfg.matrix_path(), _experimental_entry())
    blessed = bless_mod.bless(cfg, **KEY, notes="prod-ready")
    assert blessed.status == "blessed"
    assert blessed.notes == "prod-ready"

    reloaded = matrix_mod.find(matrix_mod.load(cfg.matrix_path()), **KEY)
    assert reloaded is not None
    assert reloaded.status == "blessed"


def test_bless_idempotent_on_already_blessed(cfg):
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            status="blessed",
            tested_at=matrix_mod.now_iso(),
            **KEY,
        ),
    )
    result = bless_mod.bless(cfg, **KEY)
    assert result.status == "blessed"


def test_bless_refuses_broken(cfg):
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            status="broken",
            tested_at=matrix_mod.now_iso(),
            **KEY,
        ),
    )
    with pytest.raises(bless_mod.BlessError, match="broken"):
        bless_mod.bless(cfg, **KEY)


def test_bless_requires_existing_entry(cfg):
    with pytest.raises(bless_mod.BlessError, match="no matrix entry"):
        bless_mod.bless(cfg, **KEY)


def test_bless_rejects_stale_test(cfg):
    """Tests older than the recency window are not promotable."""
    too_old = (
        datetime.now(timezone.utc) - timedelta(days=cfg.bless_recency_window_days + 1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    matrix_mod.upsert(cfg.matrix_path(), _experimental_entry(tested_at=too_old))
    with pytest.raises(bless_mod.BlessError, match="stale"):
        bless_mod.bless(cfg, **KEY)


def test_bless_accepts_recent_test(cfg):
    recent = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    matrix_mod.upsert(cfg.matrix_path(), _experimental_entry(tested_at=recent))
    blessed = bless_mod.bless(cfg, **KEY)
    assert blessed.status == "blessed"
