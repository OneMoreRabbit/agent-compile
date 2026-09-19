"""Supplementary GIDs: names from the plan, numbers from the map (ADR-0013 R6).

The defect this replaces: `AGENT_SUPP_GIDS` was read from
`local_user.supp_gids`, a field not in the v0.4 registry schema that nobody
populates — so every agent compiled with an empty set and no `group_add`. The
old behaviour was *documented* ("agent-compile defaults it to []") and still
wrong: a declared default whose consequence nobody traced.

The point of these tests is the THREE ABSENCES kept distinct. Collapsing them
is the defect; only one of the three may legitimately emit empty.
"""

from __future__ import annotations

import pytest
import yaml

from agent_compile import compile as compile_mod
from agent_compile import compose as compose_mod

AGENT = "agent_arc_marketing_bob"


def _compose(cfg):
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    return (cfg.compiled_agent_path(AGENT) / "compose.yml").read_text()


def _edit(path, fn):
    d = yaml.safe_load(path.read_text())
    fn(d)
    path.write_text(yaml.safe_dump(d))


def test_gids_come_from_the_plan_joined_to_the_map(cfg):
    """The working path: two groups, both numbered."""
    out = _compose(cfg)
    assert 'AGENT_SUPP_GIDS: "15002,15000"' in out
    assert '- "15002"' in out and '- "15000"' in out


def test_order_follows_the_plan_not_the_map(cfg):
    """Deterministic and plan-ordered, so a re-compile is byte-identical."""
    out = _compose(cfg)
    first = out.index("15002")
    second = out.index("15000")
    assert first < second, "plan lists marketing before any_global; order must follow it"


# --- absence 1: the agent is not in the plan --------------------------------

def test_agent_missing_from_the_plan_fails(cfg):
    """Cannot tell 'no groups' from 'not compiled yet'. Guessing empty is the defect."""
    _edit(cfg.compiled_plan_path(),
          lambda d: d["agent_users"].remove(
              next(e for e in d["agent_users"] if e["name"] == AGENT)))
    with pytest.raises(compose_mod.ComposeError) as e:
        _compose(cfg)
    assert "agent_users[]" in str(e.value)
    assert AGENT in str(e.value)


# --- absence 2: a named group is not in the map -----------------------------

def test_group_missing_from_the_map_fails_naming_both(cfg):
    """A plan ahead of the map is NORMAL — the map is written on assign."""
    _edit(cfg.group_gid_map_path(), lambda d: d.pop("arc_g2_marketing_global"))
    with pytest.raises(compose_mod.ComposeError) as e:
        _compose(cfg)
    msg = str(e.value)
    assert "arc_g2_marketing_global" in msg, "must name the group"
    assert str(cfg.group_gid_map_path()) in msg, "must name the file"


def test_a_partial_set_is_never_emitted(cfg):
    """The resolvable subset must not ship — that attaches partial access and reports success."""
    _edit(cfg.group_gid_map_path(), lambda d: d.pop("arc_g2_marketing_global"))
    with pytest.raises(compose_mod.ComposeError):
        _compose(cfg)
    art = cfg.compiled_agent_path(AGENT) / "compose.yml"
    if art.is_file():
        assert "15000" not in art.read_text(), "emitted the resolvable subset"


# --- absence 3: the plan says zero groups — the ONLY legitimate empty --------

def test_zero_groups_in_the_plan_emits_empty(cfg):
    """Empty is now a statement the plan makes, not residue of a missing key."""
    _edit(cfg.compiled_plan_path(),
          lambda d: next(e for e in d["agent_users"] if e["name"] == AGENT)
          .__setitem__("groups", []))
    out = _compose(cfg)
    assert 'AGENT_SUPP_GIDS: ""' in out
    assert "group_add:" not in out


def test_the_dead_registry_field_is_not_read(cfg):
    """`local_user.supp_gids` must no longer influence the emission.

    Leaving it read while the plan resolves would make it a SECOND source of
    truth — a contradicted control, worse than the phantom it was.
    """
    import agent_compile.registry as reg
    path = cfg.agent_registry_path()
    _edit(path, lambda d: next(
        a for a in d["agents"] if a["name"] == AGENT)["local_user"]
        .__setitem__("supp_gids", [99999]))
    out = _compose(cfg)
    assert "99999" not in out, "the retired registry field still reaches the emission"
    assert 'AGENT_SUPP_GIDS: "15002,15000"' in out
