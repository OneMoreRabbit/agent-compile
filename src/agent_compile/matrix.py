"""Compatibility matrix R/W.

Contract: ../../../docs/contracts/compatibility-matrix-entry-schema-v0_1.md

Both image-compile and agent-compile write here. ``ruamel.yaml`` round-trip
preserves comments and ordering so neither tool churns the other's writes.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from ruamel.yaml import YAML

_VALID_STATUS = {"blessed", "experimental", "broken"}


class MatrixError(Exception):
    pass


@dataclass
class MatrixEntry:
    flavour: str
    image: str
    template: str
    status: str
    tested_at: str
    test_agent: str = ""
    notes: str = ""

    def key(self) -> Tuple[str, str, str]:
        return (self.flavour, self.image, self.template)


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def now_iso() -> str:
    """ISO 8601 UTC, second precision, Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC string back into an aware datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def load(matrix_path: Path) -> List[MatrixEntry]:
    """Load all entries. Empty list if the file doesn't exist."""
    if not matrix_path.is_file():
        return []
    y = _yaml()
    with matrix_path.open(encoding="utf-8") as f:
        data = y.load(f) or {}
    entries_raw = data.get("entries") or []
    return [_entry_from_mapping(e) for e in entries_raw]


def _entry_from_mapping(d) -> MatrixEntry:
    for required in ("flavour", "image", "template", "status", "tested_at"):
        if required not in d:
            raise MatrixError(f"matrix entry missing required field: {required}")
    return MatrixEntry(
        flavour=str(d["flavour"]),
        image=str(d["image"]),
        template=str(d["template"]),
        status=str(d["status"]),
        tested_at=str(d["tested_at"]),
        test_agent=str(d.get("test_agent", "")),
        notes=str(d.get("notes", "")),
    )


def find(
    entries: List[MatrixEntry], flavour: str, image: str, template: str
) -> Optional[MatrixEntry]:
    for e in entries:
        if (e.flavour, e.image, e.template) == (flavour, image, template):
            return e
    return None


def upsert(matrix_path: Path, entry: MatrixEntry) -> None:
    """Upsert by (flavour, image, template). Atomic write via temp + rename."""
    if entry.status not in _VALID_STATUS:
        raise MatrixError(
            f"invalid status: {entry.status!r} (expected one of {sorted(_VALID_STATUS)})"
        )
    y = _yaml()
    if matrix_path.is_file():
        with matrix_path.open(encoding="utf-8") as f:
            data = y.load(f) or {}
    else:
        data = {}
    if "entries" not in data or data["entries"] is None:
        data["entries"] = []
    entries = data["entries"]
    key = (entry.flavour, entry.image, entry.template)
    new_dict = {
        "flavour": entry.flavour,
        "image": entry.image,
        "template": entry.template,
        "status": entry.status,
        "tested_at": entry.tested_at,
        "test_agent": entry.test_agent,
        "notes": entry.notes,
    }
    replaced = False
    for i, existing in enumerate(entries):
        if (
            str(existing.get("flavour")),
            str(existing.get("image")),
            str(existing.get("template")),
        ) == key:
            entries[i] = new_dict
            replaced = True
            break
    if not replaced:
        entries.append(new_dict)
    _atomic_write_yaml(matrix_path, data, y)


def _atomic_write_yaml(path: Path, data, y: YAML) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".new")
    buf = io.StringIO()
    y.dump(data, buf)
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    os.replace(tmp, path)
