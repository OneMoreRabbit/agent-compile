"""Snapshot a running agent's persistent state into a new template version.

Pipeline (per build brief §Snapshot mode):

1. Read the agent's registry entry. Validate flavour matches the target
   template id's flavour.
2. Resolve the agent's *current* template chain to produce the "expected"
   file content.
3. Fetch the agent's *actual* files from the agent host via SSH.
4. Strip instance-specific fields from the openclaw.json on both sides (per
   ``templates/instance-fields/<flavour>.yml``).
5. Diff:
   - ``openclaw.json`` → JSON merge patch (None deletes parent key)
   - workspace files → full-content override for any that differ
   - skills → ``add:`` entry for any directory present on host that the
     chain doesn't supply
6. Write the new template version YAML with ``parent`` = agent's current
   template id, ``derived_from.kind`` = ``instance_snapshot``.
7. Return the path to the new template YAML.

SSH calls are routed through an ``SshFetcher`` interface so tests can plug
a fake filesystem.
"""

from __future__ import annotations

import copy
import json
import shlex
import shutil
import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

import yaml

from . import agent_entry
from . import matrix as matrix_mod
from . import paths as paths_mod
from . import registry as registry_mod
from . import resolver as resolver_mod
from .config import Config
from .identifiers import IdentifierError, parse_image_ref, parse_template_id


class SnapshotError(Exception):
    pass


# --- SSH abstraction --------------------------------------------------------


class SshFetcher(Protocol):
    def fetch(self, host: str, remote_path: str) -> str:
        ...

    def list_dir(self, host: str, remote_path: str) -> List[str]:
        ...


@dataclass
class SshSubprocessFetcher:
    """Default fetcher — shells out to ``ssh`` with ``BatchMode=yes``."""

    ssh_user: str = "codetest"
    ssh_options: List[str] = field(
        default_factory=lambda: ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    )

    def _base(self, host: str) -> List[str]:
        return ["ssh", *self.ssh_options, f"{self.ssh_user}@{host}"]

    def fetch(self, host: str, remote_path: str) -> str:
        try:
            r = subprocess.run(
                [*self._base(host), "cat", shlex.quote(remote_path)],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        except subprocess.CalledProcessError as e:
            raise SnapshotError(
                f"ssh fetch failed for {host}:{remote_path}: {e.stderr.strip()}"
            ) from e
        return r.stdout

    def list_dir(self, host: str, remote_path: str) -> List[str]:
        try:
            r = subprocess.run(
                [*self._base(host), "ls", "-1", shlex.quote(remote_path)],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        except subprocess.CalledProcessError as e:
            # Directory absent → treat as empty
            if "No such file or directory" in (e.stderr or ""):
                return []
            raise SnapshotError(
                f"ssh ls failed for {host}:{remote_path}: {e.stderr.strip()}"
            ) from e
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]


# --- diff helpers -----------------------------------------------------------


_NO_DIFF = object()


def _json_merge_patch(expected: Any, actual: Any) -> Any:
    """Compute a patch P such that merging P over ``expected`` yields ``actual``.

    Convention matches our ``merge.merge_json``: ``None`` in P means "delete
    this key from the parent". Returns ``_NO_DIFF`` if no patch is needed
    (caller flattens to empty / inherit).
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        patch: Dict[str, Any] = {}
        for key in expected:
            if key not in actual:
                patch[key] = None
                continue
            sub = _json_merge_patch(expected[key], actual[key])
            if sub is _NO_DIFF:
                continue
            patch[key] = sub
        for key in actual:
            if key in expected:
                continue
            patch[key] = actual[key]
        if not patch:
            return _NO_DIFF
        return patch
    if expected == actual:
        return _NO_DIFF
    return actual


def _strip_paths(d: Dict[str, Any], paths: List[str]) -> Dict[str, Any]:
    """Return a deep copy of ``d`` with each dotted path removed (silently)."""
    out = copy.deepcopy(d)
    for path in paths:
        _delete_path(out, path.split("."))
    return out


def _delete_path(d: Any, parts: List[str]) -> None:
    if not parts or not isinstance(d, dict):
        return
    if len(parts) == 1:
        d.pop(parts[0], None)
        return
    nxt = d.get(parts[0])
    if isinstance(nxt, dict):
        _delete_path(nxt, parts[1:])


def _workspace_diff(expected: Dict[str, str], actual: Dict[str, str]) -> Dict[str, str]:
    """Return only the files that differ; values are the actual host contents."""
    out: Dict[str, str] = {}
    for name, content in actual.items():
        if expected.get(name) != content:
            out[name] = content
    return out


def _skills_diff(expected: List[str], actual_listing: List[str]) -> Dict[str, List[str]]:
    """Return ``{"add": [...]}`` for skills in ``actual`` but not ``expected``."""
    expected_set = set(expected)
    new = [s for s in actual_listing if s not in expected_set]
    if not new:
        return {}
    return {"add": new}


def _load_instance_fields(cfg: Config, flavour: str) -> List[str]:
    """Read the per-flavour scrub list. Warns when the list is stubbed."""
    rel = cfg.flavour(flavour).instance_fields_list
    path = cfg.repo_root / rel
    if not path.is_file():
        warnings.warn(
            f"instance-fields list not found: {path}; snapshot diff will keep instance fields"
        )
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if str(data.get("schema_version", "")) == "stub":
        warnings.warn(
            f"instance-fields list is stubbed at {path}; review snapshot output carefully — "
            "paths may be missed or over-stripped"
        )
    return list(data.get("paths") or [])


# --- public entry point -----------------------------------------------------


def snapshot(
    cfg: Config,
    *,
    agent_name: str,
    target_template_id_str: str,
    fetcher: Optional[SshFetcher] = None,
) -> Path:
    """Run the snapshot pipeline. Returns the path to the new template YAML."""
    agent = registry_mod.get_agent(cfg, agent_name)

    try:
        current_tid = parse_template_id(agent_entry.app_template(agent))
        target_tid = parse_template_id(target_template_id_str)
        image_ref = parse_image_ref(agent_entry.app_image(agent))
    except (IdentifierError, agent_entry.AgentEntryError, KeyError) as e:
        raise SnapshotError(f"identifier error: {e}") from e

    if current_tid.flavour != target_tid.flavour:
        raise SnapshotError(
            f"flavour mismatch: agent template {current_tid.flavour!r} "
            f"!= target template {target_tid.flavour!r}"
        )
    if image_ref.flavour != current_tid.flavour:
        raise SnapshotError(
            f"flavour mismatch: agent image {image_ref.flavour!r} "
            f"!= template {current_tid.flavour!r}"
        )

    if registry_mod.template_exists(
        cfg, target_tid.flavour, target_tid.name, target_tid.version
    ):
        raise SnapshotError(
            f"target template already exists: {target_tid}"
        )

    resolved = resolver_mod.resolve(cfg, current_tid)

    fetcher = fetcher or _default_fetcher(cfg)
    try:
        host = paths_mod.resolve_agent_host(cfg, agent)
    except paths_mod.HostResolutionError as e:
        raise SnapshotError(str(e)) from e

    host_root = paths_mod.agent_host_root(agent)
    flavour_filename = cfg.flavour(current_tid.flavour).config_filename

    try:
        actual_flavour_json = json.loads(
            fetcher.fetch(host, f"{host_root}/configs/main/{flavour_filename}")
        )
    except json.JSONDecodeError as e:
        raise SnapshotError(f"actual {flavour_filename} on host is not valid JSON: {e}") from e

    actual_workspace: Dict[str, str] = {}
    for name in ("AGENTS.md", "SOUL.md", "TOOLS.md"):
        try:
            actual_workspace[name] = fetcher.fetch(
                host, f"{host_root}/memory/main/workspace/{name}"
            )
        except SnapshotError:
            # Missing on the host → ignore (snapshot captures what's there)
            continue

    actual_skills = sorted(
        fetcher.list_dir(host, f"{host_root}/memory/main/workspace/skills")
    )

    scrub_paths = _load_instance_fields(cfg, current_tid.flavour)
    expected_scrubbed = _strip_paths(resolved.flavour_json, scrub_paths)
    actual_scrubbed = _strip_paths(actual_flavour_json, scrub_paths)
    json_patch = _json_merge_patch(expected_scrubbed, actual_scrubbed)
    overrides_json = {} if json_patch is _NO_DIFF else json_patch

    workspace_overrides = _workspace_diff(resolved.workspace, actual_workspace)
    skills_overrides = _skills_diff(resolved.skills, actual_skills)

    new_tpl = registry_mod.Template(
        flavour=target_tid.flavour,
        name=target_tid.name,
        version=target_tid.version,
        parent=str(current_tid),
        description=f"Snapshot of {agent_name} at {matrix_mod.now_iso()}",
        derived_from={
            "kind": "instance_snapshot",
            "source": agent_name,
            "at": matrix_mod.now_iso(),
        },
        overrides={
            "openclaw_json": overrides_json,
            "workspace": workspace_overrides,
            "skills": skills_overrides,
        },
        secret_manifest=[],
        preferred_image=str(image_ref),
    )
    return registry_mod.save_template(cfg, new_tpl)


def _default_fetcher(cfg: Config) -> SshFetcher:
    snap = cfg.raw.get("snapshot") or {}
    ssh_user = str(snap.get("ssh_user", "codetest"))
    options = snap.get("ssh_options") or [
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
    ]
    return SshSubprocessFetcher(ssh_user=ssh_user, ssh_options=list(options))
