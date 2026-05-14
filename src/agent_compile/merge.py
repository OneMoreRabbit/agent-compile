"""Override merge semantics for template chain resolution.

Three rules from the build brief §Override merge semantics:

- ``openclaw_json``: deep-merge with ``None`` deletes the key.
- ``workspace``: whole-file replacement (no line-level merging).
- ``skills``: set union by name; parent order preserved.
"""

from __future__ import annotations

from typing import Any, Dict, List


def merge_json(parent: Any, override: Any) -> Any:
    """Deep-merge ``override`` onto ``parent``.

    Rules:

    - dict + dict: recurse key-wise.
    - list + list: replace (don't append).
    - scalar + scalar: replace.
    - anything + None: delete the key from parent.
    - absent + value: add (unless value is None).
    - value + absent: inherit.

    Returns a new value; does not mutate the inputs.
    """
    if isinstance(parent, dict) and isinstance(override, dict):
        result: Dict[str, Any] = {}
        for key in parent:
            if key in override:
                if override[key] is None:
                    continue  # delete
                result[key] = merge_json(parent[key], override[key])
            else:
                result[key] = parent[key]
        for key in override:
            if key in parent:
                continue
            if override[key] is None:
                continue  # null on absent key: no-op
            result[key] = override[key]
        return result
    if isinstance(parent, list) and isinstance(override, list):
        return list(override)
    return override


def merge_workspace(parent: Dict[str, str], override: Dict[str, str]) -> Dict[str, str]:
    """Whole-file replacement. Files not mentioned in ``override`` are inherited."""
    result = dict(parent)
    for filename, content in (override or {}).items():
        result[filename] = content
    return result


def merge_skills(parent: List[str], override: Dict[str, Any]) -> List[str]:
    """Set union by skill name. Parent order preserved; additions appended in their listed order.

    Removal is not supported in MVP (see build brief).
    """
    result = list(parent)
    add = (override or {}).get("add") or []
    for skill in add:
        if skill not in result:
            result.append(skill)
    return result
