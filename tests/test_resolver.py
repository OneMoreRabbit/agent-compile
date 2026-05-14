"""Tests for chain resolution, cycle detection, and cross-flavour rejection."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_compile import config as config_mod
from agent_compile import resolver as resolver_mod
from agent_compile.identifiers import TemplateID


# --- Simple chain resolution -----------------------------------------------


def test_resolve_v1_chain(cfg):
    leaf = TemplateID("openclaw", "marketing_arc", 1)
    r = resolver_mod.resolve(cfg, leaf)
    assert r.flavour == "openclaw"
    assert r.image_version == "2026.5.5-r1"
    assert r.from_chain == [
        "image_defaults:openclaw:2026.5.5-r1",
        "openclaw:marketing_arc:v1",
    ]
    # v1 enables discord and overrides dmPolicy to "free"
    assert r.flavour_json["channels"]["discord"]["enabled"] is True
    assert r.flavour_json["channels"]["discord"]["dmPolicy"] == "free"
    # SOUL.md replaced by v1
    assert "Marketing agent persona" in r.workspace["SOUL.md"]
    # AGENTS.md inherited from baseline
    assert "openclaw 2026.5.5-r1 baseline" in r.workspace["AGENTS.md"]
    # skills added
    assert r.skills == ["social_channel_etiquette"]
    # secrets added
    assert r.secret_manifest == ["SOCIAL_API_KEY"]


def test_resolve_v2_chain_applies_root_to_leaf(cfg):
    """v2 chain: image_defaults -> v1 -> v2.

    v1 sets dmPolicy=free; v2 overrides it to "pairing". Leaf wins.
    """
    leaf = TemplateID("openclaw", "marketing_arc", 2)
    r = resolver_mod.resolve(cfg, leaf)
    assert r.from_chain == [
        "image_defaults:openclaw:2026.5.5-r1",
        "openclaw:marketing_arc:v1",
        "openclaw:marketing_arc:v2",
    ]
    # Leaf wins: dmPolicy=pairing (set by v2 after v1's "free")
    assert r.flavour_json["channels"]["discord"]["dmPolicy"] == "pairing"
    # v1's enabled=true still in effect
    assert r.flavour_json["channels"]["discord"]["enabled"] is True
    # SOUL.md from v1, AGENTS.md from v2
    assert "Marketing agent persona" in r.workspace["SOUL.md"]
    assert "v2 guidance" in r.workspace["AGENTS.md"]
    # skills union, parent order preserved
    assert r.skills == ["social_channel_etiquette", "dprox_query"]


def test_resolve_deterministic(cfg):
    """Two consecutive resolves of the same leaf produce equivalent results."""
    leaf = TemplateID("openclaw", "marketing_arc", 2)
    a = resolver_mod.resolve(cfg, leaf)
    b = resolver_mod.resolve(cfg, leaf)
    assert a.flavour_json == b.flavour_json
    assert a.workspace == b.workspace
    assert a.skills == b.skills
    assert a.secret_manifest == b.secret_manifest


# --- Cross-flavour rejection -----------------------------------------------


def _write_template(registry_root: Path, flavour: str, name: str, version: int, content: str) -> None:
    p = registry_root / "agent_templates" / flavour / name / f"v{version}.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_cross_flavour_parent_rejected(fixture_registry: Path):
    """A template whose parent is `image_defaults:<other-flavour>:...` is rejected."""
    _write_template(
        fixture_registry,
        "openclaw",
        "weird",
        1,
        """\
name: weird
version: 1
flavour: openclaw
parent: image_defaults:nanoclaw:1.2.3-r1
description: "cross-flavour parent"
overrides: {}
""",
    )
    cfg = config_mod.load(registry_root_override=fixture_registry)
    with pytest.raises(resolver_mod.FlavourMismatchError):
        resolver_mod.resolve(cfg, TemplateID("openclaw", "weird", 1))


def test_cross_flavour_template_parent_rejected(fixture_registry: Path):
    """A template whose parent is a template of a different flavour is rejected.

    walk_chain catches this at parse time before it can load the wrong file.
    """
    _write_template(
        fixture_registry,
        "openclaw",
        "weird",
        1,
        """\
name: weird
version: 1
flavour: openclaw
parent: nanoclaw:light_assistant:v1
description: "cross-flavour template parent"
overrides: {}
""",
    )
    cfg = config_mod.load(registry_root_override=fixture_registry)
    with pytest.raises(resolver_mod.FlavourMismatchError):
        resolver_mod.resolve(cfg, TemplateID("openclaw", "weird", 1))


# --- Cycle detection -------------------------------------------------------


def test_direct_cycle_detected(fixture_registry: Path):
    """A → B → A direct cycle."""
    _write_template(
        fixture_registry,
        "openclaw",
        "loop_a",
        1,
        """\
name: loop_a
version: 1
flavour: openclaw
parent: openclaw:loop_b:v1
description: "half of A -> B -> A cycle"
overrides: {}
""",
    )
    _write_template(
        fixture_registry,
        "openclaw",
        "loop_b",
        1,
        """\
name: loop_b
version: 1
flavour: openclaw
parent: openclaw:loop_a:v1
description: "other half"
overrides: {}
""",
    )
    cfg = config_mod.load(registry_root_override=fixture_registry)
    with pytest.raises(resolver_mod.CycleError):
        resolver_mod.resolve(cfg, TemplateID("openclaw", "loop_a", 1))


def test_indirect_cycle_detected(fixture_registry: Path):
    """A → B → C → A indirect cycle."""
    _write_template(
        fixture_registry,
        "openclaw",
        "c_a",
        1,
        "name: c_a\nversion: 1\nflavour: openclaw\nparent: openclaw:c_b:v1\noverrides: {}\n",
    )
    _write_template(
        fixture_registry,
        "openclaw",
        "c_b",
        1,
        "name: c_b\nversion: 1\nflavour: openclaw\nparent: openclaw:c_c:v1\noverrides: {}\n",
    )
    _write_template(
        fixture_registry,
        "openclaw",
        "c_c",
        1,
        "name: c_c\nversion: 1\nflavour: openclaw\nparent: openclaw:c_a:v1\noverrides: {}\n",
    )
    cfg = config_mod.load(registry_root_override=fixture_registry)
    with pytest.raises(resolver_mod.CycleError):
        resolver_mod.resolve(cfg, TemplateID("openclaw", "c_a", 1))


# --- Self-cycle (template parent = itself) ---------------------------------


def test_self_cycle_detected(fixture_registry: Path):
    _write_template(
        fixture_registry,
        "openclaw",
        "selfish",
        1,
        "name: selfish\nversion: 1\nflavour: openclaw\nparent: openclaw:selfish:v1\noverrides: {}\n",
    )
    cfg = config_mod.load(registry_root_override=fixture_registry)
    with pytest.raises(resolver_mod.CycleError):
        resolver_mod.resolve(cfg, TemplateID("openclaw", "selfish", 1))


# --- walk_chain ordering ---------------------------------------------------


def test_walk_chain_root_to_leaf_order(cfg):
    leaf = TemplateID("openclaw", "marketing_arc", 2)
    root_ref, chain = resolver_mod.walk_chain(cfg, leaf)
    assert root_ref.flavour == "openclaw"
    assert root_ref.image_version == "2026.5.5-r1"
    # chain returned root → leaf
    assert [t.version for t in chain] == [1, 2]
    assert [t.name for t in chain] == ["marketing_arc", "marketing_arc"]
