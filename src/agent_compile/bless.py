"""Matrix bless logic.

Promote an ``experimental`` matrix entry to ``blessed``. Requires:

- An existing entry with the given ``(flavour, image, template)`` key.
- Status must be ``experimental`` (not ``broken``, not already ``blessed``).
- ``tested_at`` must be within ``bless.recency_window_days`` of now
  (default 30; configurable via ``config.yml``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import matrix as matrix_mod
from .config import Config


class BlessError(Exception):
    pass


def bless(
    cfg: Config,
    *,
    flavour: str,
    image: str,
    template: str,
    notes: str = "",
) -> matrix_mod.MatrixEntry:
    """Promote an experimental entry to blessed."""
    entries = matrix_mod.load(cfg.matrix_path())
    existing = matrix_mod.find(entries, flavour, image, template)
    if existing is None:
        raise BlessError(
            f"no matrix entry to bless: ({flavour}, {image}, {template})"
        )
    if existing.status == "broken":
        raise BlessError(
            f"refusing to bless broken entry: ({flavour}, {image}, {template})"
        )
    if existing.status == "blessed":
        # Idempotent: already blessed
        return existing

    tested_at = matrix_mod.parse_iso(existing.tested_at)
    age = datetime.now(timezone.utc) - tested_at
    window = timedelta(days=cfg.bless_recency_window_days)
    if age > window:
        raise BlessError(
            f"test record is stale ({age.days}d > {window.days}d window): "
            f"({flavour}, {image}, {template})"
        )

    blessed = matrix_mod.MatrixEntry(
        flavour=flavour,
        image=image,
        template=template,
        status="blessed",
        tested_at=existing.tested_at,
        test_agent=existing.test_agent,
        notes=notes or existing.notes,
    )
    matrix_mod.upsert(cfg.matrix_path(), blessed)
    return blessed
