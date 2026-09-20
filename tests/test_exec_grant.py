"""The exec grant and the standing privilege closures (ADR-0013 D5 + amendments).

Every execution- or privilege-shaped gate the schema exposes is emitted CLOSED
unless the registry names it. Omission is not denial: neither `exec.security`
nor `exec.mode` declares a default in the 6.35 schema, and agent-image's source
read says omission likely resolves to `full` — so an agent that merely lacks
the block is exec-capable.
"""

from __future__ import annotations

import json

import yaml

from agent_compile import compile as compile_mod

AGENT = "agent_arc_marketing_bob"


def _grant(cfg):
    path = cfg.agent_registry_path()
    d = yaml.safe_load(path.read_text())
    next(a for a in d["agents"] if a["name"] == AGENT)["app"]["exec"] = {}
    path.write_text(yaml.safe_dump(d))


def _tools(cfg):
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    art = cfg.compiled_agent_path(AGENT) / cfg.flavour("openclaw").config_filename
    return json.loads(art.read_text())["tools"]


def test_no_grant_closes_every_spelling(cfg):
    """Absence of `app.exec` must deny through each door, not by omission."""
    t = _tools(cfg)
    assert t["exec"]["security"] == "deny"
    assert t["exec"]["mode"] == "deny", "6.35 added `mode` beside `security`, no precedence stated"
    assert "exec" in t["deny"]
    assert "exec" not in (t.get("allow") or [])
    assert "exec" not in (t.get("alsoAllow") or [])


def test_a_grant_opens_exec_explicitly(cfg):
    """Granted is also stated, not defaulted — the same argument in reverse."""
    _grant(cfg)
    t = _tools(cfg)
    assert t["exec"]["security"] == "full"
    assert t["exec"]["mode"] == "full"
    assert "exec" not in (t.get("deny") or [])


def test_presence_is_the_grant_no_enabled_key(cfg):
    """An empty `app.exec` block grants. There is no `enabled:` to get wrong."""
    path = cfg.agent_registry_path()
    d = yaml.safe_load(path.read_text())
    next(a for a in d["agents"] if a["name"] == AGENT)["app"]["exec"] = {}
    path.write_text(yaml.safe_dump(d))
    assert _tools(cfg)["exec"]["security"] == "full"


def test_elevated_is_closed_for_every_agent(cfg):
    """Privilege-shaped and unexamined: closed and stated whether granted or not."""
    assert _tools(cfg)["elevated"] == {"enabled": False}
    _grant(cfg)
    assert _tools(cfg)["elevated"] == {"enabled": False}


def test_codemode_is_closed_for_every_agent(cfg):
    """A QuickJS runtime is a hand, and no registry grant names it today.

    Sandboxed is not the question. If an agent someday wants sandboxed code
    without a shell, that is a new registry-visible grant designed then — not a
    door left ajar because its walls look thick.
    """
    assert _tools(cfg)["codeMode"] == {"enabled": False}
    _grant(cfg)
    assert _tools(cfg)["codeMode"] == {"enabled": False}


def test_gates_are_emitted_in_every_tools_node(cfg):
    """Top level AND each agents.list[] entry — precedence between them is unstated.

    A denial in only one place is a denial only if the other does not win.
    """
    bundle = (cfg.image_defaults_path("openclaw", "2026.5.5-r1") / "openclaw.json")
    j = json.loads(bundle.read_text())
    j["agents"] = {"list": [{"id": "main", "tools": {"exec": {"security": "full"}}}]}
    bundle.write_text(json.dumps(j))

    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    art = cfg.compiled_agent_path(AGENT) / cfg.flavour("openclaw").config_filename
    out = json.loads(art.read_text())
    assert out["tools"]["exec"]["security"] == "deny", "top-level not closed"
    entry = out["agents"]["list"][0]
    assert entry["tools"]["exec"]["security"] == "deny", "per-entry not closed"
    assert entry["tools"]["exec"]["mode"] == "deny"
    assert entry["id"] == "main", "must not disturb the entry's own keys"


def test_an_allow_list_cannot_smuggle_exec_past_a_no_grant(cfg):
    """A template granting exec via `allow` must not defeat the registry."""
    bundle = (cfg.image_defaults_path("openclaw", "2026.5.5-r1") / "openclaw.json")
    j = json.loads(bundle.read_text())
    j["tools"] = {"allow": ["exec", "fs"], "alsoAllow": ["exec"]}
    bundle.write_text(json.dumps(j))
    t = _tools(cfg)
    assert "exec" not in t["allow"] and "fs" in t["allow"], "stripped too much or too little"
    assert "exec" not in t["alsoAllow"]
    assert "exec" in t["deny"]
