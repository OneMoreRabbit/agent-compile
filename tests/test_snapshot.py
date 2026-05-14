"""Tests for the snapshot pipeline.

Real SSH is mocked through a ``FakeFetcher`` that reads from an in-memory dict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List

import pytest

from agent_compile import compile as compile_mod
from agent_compile import registry as registry_mod
from agent_compile import resolver as resolver_mod
from agent_compile import snapshot as snapshot_mod
from agent_compile.identifiers import parse_template_id


AGENT = "agent_arc_marketing_bob"


@dataclass
class FakeFetcher:
    files: Dict[str, str] = field(default_factory=dict)
    dirs: Dict[str, List[str]] = field(default_factory=dict)

    def fetch(self, host: str, remote_path: str) -> str:
        key = f"{host}:{remote_path}"
        if key not in self.files:
            raise snapshot_mod.SnapshotError(f"missing file {key}")
        return self.files[key]

    def list_dir(self, host: str, remote_path: str) -> List[str]:
        return list(self.dirs.get(f"{host}:{remote_path}", []))


def _build_fetcher_from_compile(cfg) -> FakeFetcher:
    """Run compile_agent, then take its artifacts as the 'actual' on-host content.

    This represents the no-drift case: a freshly-deployed agent. The snapshot
    diff should be near-empty (only instance fields differ, all scrubbed).
    """
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    art = cfg.compiled_agent_path(AGENT)
    flavour_filename = cfg.flavour("openclaw").config_filename
    flavour_json_text = (art / flavour_filename).read_text(encoding="utf-8")

    host = "marten"
    root = f"/mnt/raid/arc/agents/{AGENT}"
    fetcher = FakeFetcher()
    fetcher.files[f"{host}:{root}/configs/main/{flavour_filename}"] = flavour_json_text
    for name in ("AGENTS.md", "SOUL.md", "TOOLS.md"):
        fetcher.files[
            f"{host}:{root}/memory/main/workspace/{name}"
        ] = (art / "workspace" / name).read_text(encoding="utf-8")
    fetcher.dirs[f"{host}:{root}/memory/main/workspace/skills"] = [
        d.name for d in (art / "workspace" / "skills").iterdir() if d.is_dir()
    ]
    return fetcher


# --- happy path -------------------------------------------------------------


def test_snapshot_writes_new_template_yaml(cfg):
    fetcher = _build_fetcher_from_compile(cfg)
    path = snapshot_mod.snapshot(
        cfg,
        agent_name=AGENT,
        target_template_id_str="openclaw:marketing_arc:v3",
        fetcher=fetcher,
    )
    assert path.is_file()
    tpl = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 3)
    assert tpl.parent == "openclaw:marketing_arc:v1"
    assert tpl.derived_from["kind"] == "instance_snapshot"
    assert tpl.derived_from["source"] == AGENT


def test_snapshot_with_no_drift_has_minimal_overrides(cfg):
    """An agent freshly compiled and 'on host' should produce an essentially-empty patch."""
    fetcher = _build_fetcher_from_compile(cfg)
    snapshot_mod.snapshot(
        cfg,
        agent_name=AGENT,
        target_template_id_str="openclaw:marketing_arc:v3",
        fetcher=fetcher,
    )
    tpl = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 3)
    # instance-fields are scrubbed, so the json patch should be empty/near-empty
    assert tpl.overrides["workspace"] == {}
    # skills come from the resolved chain — no drift = no new skills
    assert tpl.overrides["skills"] == {}


def test_snapshot_captures_workspace_drift(cfg):
    """A modified SOUL.md on host shows up as a workspace override."""
    fetcher = _build_fetcher_from_compile(cfg)
    host = "marten"
    root = f"/mnt/raid/arc/agents/{AGENT}"
    fetcher.files[f"{host}:{root}/memory/main/workspace/SOUL.md"] = (
        "# Drifted soul\nNew content authored on the agent host.\n"
    )
    snapshot_mod.snapshot(
        cfg,
        agent_name=AGENT,
        target_template_id_str="openclaw:marketing_arc:v3",
        fetcher=fetcher,
    )
    tpl = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 3)
    assert "SOUL.md" in tpl.overrides["workspace"]
    assert "Drifted soul" in tpl.overrides["workspace"]["SOUL.md"]


def test_snapshot_captures_new_skill(cfg):
    """A skill present on the host but not in the chain should appear in skills.add."""
    fetcher = _build_fetcher_from_compile(cfg)
    host = "marten"
    root = f"/mnt/raid/arc/agents/{AGENT}"
    fetcher.dirs[f"{host}:{root}/memory/main/workspace/skills"] = [
        "social_channel_etiquette",
        "new_runtime_skill",
    ]
    snapshot_mod.snapshot(
        cfg,
        agent_name=AGENT,
        target_template_id_str="openclaw:marketing_arc:v3",
        fetcher=fetcher,
    )
    tpl = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 3)
    assert tpl.overrides["skills"].get("add") == ["new_runtime_skill"]


def test_snapshot_strips_instance_fields(cfg):
    """The on-host openclaw.json has the agent's real name + dprox endpoint;
    snapshot must not capture those in the template delta's overrides block."""
    fetcher = _build_fetcher_from_compile(cfg)
    snapshot_mod.snapshot(
        cfg,
        agent_name=AGENT,
        target_template_id_str="openclaw:marketing_arc:v3",
        fetcher=fetcher,
    )
    tpl = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 3)
    # Overrides must not carry instance-specific values — those are scrubbed.
    overrides_blob = json.dumps(tpl.overrides)
    assert "agent_arc_marketing_bob" not in overrides_blob
    assert "dprox.arc.internal" not in overrides_blob


# --- failure modes ----------------------------------------------------------


def test_snapshot_rejects_existing_target(cfg):
    fetcher = _build_fetcher_from_compile(cfg)
    with pytest.raises(snapshot_mod.SnapshotError, match="already exists"):
        snapshot_mod.snapshot(
            cfg,
            agent_name=AGENT,
            target_template_id_str="openclaw:marketing_arc:v2",
            fetcher=fetcher,
        )


def test_snapshot_rejects_cross_flavour(cfg):
    fetcher = _build_fetcher_from_compile(cfg)
    with pytest.raises(snapshot_mod.SnapshotError, match="flavour"):
        snapshot_mod.snapshot(
            cfg,
            agent_name=AGENT,
            target_template_id_str="nanoclaw:marketing_arc:v3",
            fetcher=fetcher,
        )


def test_snapshot_warns_when_scrub_list_is_stub(cfg, recwarn):
    fetcher = _build_fetcher_from_compile(cfg)
    snapshot_mod.snapshot(
        cfg,
        agent_name=AGENT,
        target_template_id_str="openclaw:marketing_arc:v3",
        fetcher=fetcher,
    )
    assert any("stubbed" in str(w.message) for w in recwarn.list)


def test_snapshot_unknown_agent(cfg):
    fetcher = FakeFetcher()
    with pytest.raises(registry_mod.RegistryError, match="not found"):
        snapshot_mod.snapshot(
            cfg,
            agent_name="agent_does_not_exist",
            target_template_id_str="openclaw:marketing_arc:v3",
            fetcher=fetcher,
        )


# --- merge-patch primitive --------------------------------------------------


def test_json_merge_patch_no_diff_returns_sentinel():
    assert snapshot_mod._json_merge_patch({"a": 1}, {"a": 1}) is snapshot_mod._NO_DIFF


def test_json_merge_patch_adds_keys():
    patch = snapshot_mod._json_merge_patch({"a": 1}, {"a": 1, "b": 2})
    assert patch == {"b": 2}


def test_json_merge_patch_deletes_with_none():
    patch = snapshot_mod._json_merge_patch({"a": 1, "b": 2}, {"a": 1})
    assert patch == {"b": None}


def test_json_merge_patch_nested():
    patch = snapshot_mod._json_merge_patch(
        {"a": {"x": 1, "y": 2}}, {"a": {"x": 1, "y": 99, "z": 3}}
    )
    assert patch == {"a": {"y": 99, "z": 3}}


def test_strip_paths_removes_dotted_paths():
    d = {"agent": {"name": "x"}, "dprox": {"endpoint": "y"}, "channels": {"discord": {"enabled": True}}}
    out = snapshot_mod._strip_paths(d, ["agent.name", "dprox.endpoint"])
    assert out == {"agent": {}, "dprox": {}, "channels": {"discord": {"enabled": True}}}


def test_strip_paths_ignores_missing():
    d = {"agent": {"name": "x"}}
    out = snapshot_mod._strip_paths(d, ["doesnt.exist"])
    assert out == {"agent": {"name": "x"}}
