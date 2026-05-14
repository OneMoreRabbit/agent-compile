"""Tests for the ``verify`` checker."""

from __future__ import annotations

from agent_compile import compile as compile_mod
from agent_compile import matrix as matrix_mod
from agent_compile import verify as verify_mod


AGENT = "agent_arc_marketing_bob"
KEY = dict(flavour="openclaw", image="2026.5.5-r1", template="marketing_arc:v1")


def _bless_key(cfg):
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            status="blessed",
            tested_at=matrix_mod.now_iso(),
            **KEY,
        ),
    )


def test_verify_ok_when_compiled_and_blessed(cfg):
    _bless_key(cfg)
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    result = verify_mod.verify_agent(cfg, AGENT)
    assert result.ok, result.failures


def test_verify_fails_when_no_matrix_entry(cfg):
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    result = verify_mod.verify_agent(cfg, AGENT)
    assert not result.ok
    assert any("no matrix entry" in f for f in result.failures)


def test_verify_fails_when_matrix_broken(cfg):
    """Compile against a healthy matrix first, then poison the entry, then verify."""
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            status="broken",
            tested_at=matrix_mod.now_iso(),
            **KEY,
        ),
    )
    result = verify_mod.verify_agent(cfg, AGENT)
    assert not result.ok
    assert any("broken" in f for f in result.failures)


def test_verify_fails_when_experimental(cfg):
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            status="experimental",
            tested_at=matrix_mod.now_iso(),
            **KEY,
        ),
    )
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    result = verify_mod.verify_agent(cfg, AGENT)
    assert not result.ok
    assert any("experimental" in w for w in result.warnings)


def test_verify_fails_when_artifacts_missing(cfg):
    _bless_key(cfg)
    # Do NOT compile
    result = verify_mod.verify_agent(cfg, AGENT)
    assert not result.ok
    assert any("artifacts directory missing" in f for f in result.failures)


def test_verify_fails_when_agent_missing(cfg):
    _bless_key(cfg)
    result = verify_mod.verify_agent(cfg, "no_such_agent")
    assert not result.ok


def test_verify_fails_when_image_bundle_missing(cfg):
    """Image-defaults bundle removal makes verify report a failure."""
    _bless_key(cfg)
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    import shutil

    shutil.rmtree(cfg.image_defaults_path("openclaw", "2026.5.5-r1"))
    result = verify_mod.verify_agent(cfg, AGENT)
    assert not result.ok
    assert any("image_defaults bundle missing" in f for f in result.failures)
