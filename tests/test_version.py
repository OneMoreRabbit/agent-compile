"""CLI version string — semver plus the git revision of an editable checkout."""

from __future__ import annotations

import re

from agent_compile import __version__
from agent_compile.__main__ import _display_version, _git_short_rev


def test_display_version_starts_with_semver():
    assert _display_version().startswith(__version__)


def test_git_short_rev_is_seven_hex_or_none():
    rev = _git_short_rev()
    assert rev is None or re.fullmatch(r"[0-9a-f]{7}", rev)
