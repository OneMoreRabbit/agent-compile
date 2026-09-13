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
    # ADR-0010 §7: two declared roots. `host_root` is retired.
    "beaver_root": "/mnt/raid/arc/agents/tpl_shape_check",
    "local_root": "/srv/agents/arc/tpl_shape_check",
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


# --- ADR-0010 §7 ------------------------------------------------------------

def test_every_template_mounts_the_three_surfaces_locally():
    """memory/sessions/scratch bind from the host root; configs stays on beaver.

    Asserted per schema dir, because the template is chosen by `image_version`:
    an older schema is a live selector, not a historical artefact, so a
    template left on beaver paths would break exactly the agents still on that
    image.
    """
    import jinja2

    assert SCHEMA_DIRS, "no schema template dirs found — guard would pass vacuously"
    for d in SCHEMA_DIRS:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(d)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=jinja2.StrictUndefined,
        )
        out = env.get_template("compose.yml.j2").render(**RENDER_CONTEXT)
        for surface in ("memory", "sessions", "scratch"):
            assert (
                f"/srv/agents/arc/tpl_shape_check/{surface}:/agent/{surface}" in out
            ), f"{d.name}: {surface} is not a local bind"
        assert (
            "/mnt/raid/arc/agents/tpl_shape_check/configs:/agent/configs" in out
        ), f"{d.name}: configs must stay on beaver"
        # The asymmetry mistake, asserted against rendered output.
        assert "/srv/agents/arc/agents/" not in out, f"{d.name}: stray agents/ segment"


def test_a_template_using_the_retired_variable_fails_to_render():
    """StrictUndefined is the control (ADR-0010 §7).

    A template that missed the rename — bundle-supplied or local, current or
    three schema versions old — must fail at render rather than emit
    `/configs:/agent/configs`, which is what jinja2's default Undefined
    produces: an absolute path to the host root, plausible and wrong.
    """
    import jinja2

    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    with pytest.raises(jinja2.UndefinedError):
        env.from_string("- {{ host_root }}/configs:/agent/configs:rw").render(
            **RENDER_CONTEXT
        )

    # And the failure it prevents, shown explicitly.
    lax = jinja2.Environment()
    assert (
        lax.from_string("- {{ host_root }}/configs:/agent/configs:rw").render()
        == "- /configs:/agent/configs:rw"
    )
