"""Shape checks for every per-schema compose template in the repo tree.

Authoring ``templates/<flavour>/v<upstream>/compose.yml.j2`` is a per-upstream
chore (see the new-upstream checklist in the user manual); this test sweeps
whatever schema dirs exist so a malformed or contract-breaking template fails
fast. It cannot catch a *missing* dir for a new upstream — that surfaces as
ComposeError at compile time.
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRS = sorted((REPO_ROOT / "templates" / "openclaw").glob("v*"))

RENDER_CONTEXT = {
    "agent_name": "tpl_shape_check",
    "ghcr_org": "jobcpf",
    "image_line": "openclaw-runtime",
    "image_version": "0000.0.0-r0",
    "uid": 1000,
    "primary_gid": 1000,
    "supp_gids": [],
    "supp_gids_str": "",
    "host_root": "/mnt/raid/arc/agents/tpl_shape_check",
    "local_port": 18000,
    "default_port": 8000,
    "health_endpoint": "/healthz",
}


def test_schema_template_dirs_exist():
    assert SCHEMA_DIRS, "no templates/openclaw/v* dirs found"


@pytest.mark.parametrize("schema_dir", SCHEMA_DIRS, ids=lambda p: p.name)
def test_compose_template_renders_with_contract_shape(schema_dir: Path):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(schema_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    text = env.get_template("compose.yml.j2").render(**RENDER_CONTEXT)
    # Four-surface mount contract
    for surface in ("configs", "memory", "sessions", "scratch"):
        assert f"/agent/{surface}:rw" in text, f"{schema_dir.name}: {surface} mount missing"
    # Port publish stays loopback-only
    assert "127.0.0.1:" in text, f"{schema_dir.name}: port publish is not loopback"
    # No env_file: docker compose cannot read the 0600 secrets.env (wrapper r3+)
    assert "env_file" not in text, f"{schema_dir.name}: env_file must not appear"
