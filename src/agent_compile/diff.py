"""Human-readable diff of two resolved templates."""

from __future__ import annotations

import difflib
from typing import Any, Dict, Iterator, List, Tuple

from .resolver import ResolvedTemplate


_MISSING = object()


def _walk_json(d: Any, prefix: str = "") -> Iterator[Tuple[str, Any]]:
    """Yield (dotted-path, leaf-value) pairs. Dicts recurse, lists treated as leaves."""
    if isinstance(d, dict):
        for k, v in d.items():
            sub = f"{prefix}.{k}" if prefix else k
            yield from _walk_json(v, sub)
    else:
        yield prefix, d


def json_diff(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """Flat path-level diff. Returns human-readable lines."""
    a_paths = dict(_walk_json(a))
    b_paths = dict(_walk_json(b))
    all_paths = sorted(set(a_paths) | set(b_paths))
    out: List[str] = []
    for path in all_paths:
        av = a_paths.get(path, _MISSING)
        bv = b_paths.get(path, _MISSING)
        if av == bv:
            continue
        if av is _MISSING:
            out.append(f"  + {path}: {bv!r}")
        elif bv is _MISSING:
            out.append(f"  - {path}: {av!r}")
        else:
            out.append(f"  ~ {path}: {av!r} -> {bv!r}")
    return out


def workspace_diff(a: Dict[str, str], b: Dict[str, str]) -> List[str]:
    """Unified-diff per file. Empty list if no changes."""
    out: List[str] = []
    filenames = sorted(set(a) | set(b))
    for name in filenames:
        a_lines = a.get(name, "").splitlines(keepends=True)
        b_lines = b.get(name, "").splitlines(keepends=True)
        if a_lines == b_lines:
            continue
        ud = list(
            difflib.unified_diff(
                a_lines, b_lines, fromfile=f"a/{name}", tofile=f"b/{name}", n=2
            )
        )
        out.extend(line.rstrip("\n") for line in ud)
    return out


def skills_diff(a: List[str], b: List[str]) -> List[str]:
    a_set, b_set = set(a), set(b)
    out: List[str] = []
    for s in sorted(b_set - a_set):
        out.append(f"  + {s}")
    for s in sorted(a_set - b_set):
        out.append(f"  - {s}")
    return out


def format_diff(a: ResolvedTemplate, b: ResolvedTemplate) -> str:
    """Format a full diff between two resolved templates."""
    sections: List[str] = []
    sections.append(f"chain a: {' -> '.join(a.from_chain)}")
    sections.append(f"chain b: {' -> '.join(b.from_chain)}")
    sections.append("")

    if a.flavour != b.flavour:
        sections.append(f"flavour: {a.flavour} -> {b.flavour}")
    if a.image_version != b.image_version:
        sections.append(f"image_version: {a.image_version} -> {b.image_version}")

    json_lines = json_diff(a.flavour_json, b.flavour_json)
    if json_lines:
        sections.append("flavour json:")
        sections.extend(json_lines)
    else:
        sections.append("flavour json: (no changes)")

    ws_lines = workspace_diff(a.workspace, b.workspace)
    if ws_lines:
        sections.append("workspace:")
        sections.extend(ws_lines)
    else:
        sections.append("workspace: (no changes)")

    skill_lines = skills_diff(a.skills, b.skills)
    if skill_lines:
        sections.append("skills:")
        sections.extend(skill_lines)
    else:
        sections.append("skills: (no changes)")

    secrets_lines = skills_diff(a.secret_manifest, b.secret_manifest)
    if secrets_lines:
        sections.append("secret_manifest:")
        sections.extend(secrets_lines)
    else:
        sections.append("secret_manifest: (no changes)")

    return "\n".join(sections)
