"""ghcr.org is a declared fact, never a default.

AgentEco GHCR ruling, 2026-09-13: no fallback namespace anywhere in the estate.
A silent default for a cross-component identity is a defect whatever value it
holds — `agent-compile` writes this namespace into every compiled `compose.yml`
and into what `template test` pulls, so an invented one reaches production
without anyone copying a file or reading a doc.
"""

import re
from pathlib import Path

import pytest
import yaml

from agent_compile import config as config_mod


def _write_config(tmp_path, ghcr_block):
    """A minimal config.yml, with the ghcr block spelled by the caller."""
    raw = yaml.safe_load((config_mod._default_config_path()).read_text())
    if ghcr_block is None:
        raw.pop("ghcr", None)
    else:
        raw["ghcr"] = ghcr_block
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))
    return path


@pytest.mark.parametrize(
    "ghcr_block",
    [None, {}, {"org": ""}, {"org": "   "}],
    ids=["block-absent", "block-empty", "org-empty", "org-whitespace"],
)
def test_missing_ghcr_org_is_an_error_not_a_default(tmp_path, ghcr_block):
    """Absent or blank `ghcr.org` fails closed, naming the file."""
    path = _write_config(tmp_path, ghcr_block)
    with pytest.raises(ValueError) as e:
        config_mod.load(config_path=path, registry_root_override=tmp_path)
    msg = str(e.value)
    assert "ghcr.org" in msg
    assert str(path) in msg


def test_no_fallback_namespace_anywhere_in_the_loader(tmp_path):
    """No namespace literal survives as a fallback.

    Guards the regression directly: the loader used to default to `arcpower`,
    a namespace that appears in no ruling and serves no image. If anyone
    reintroduces a fallback, this fails whatever value they pick.
    """
    path = _write_config(tmp_path, None)
    with pytest.raises(ValueError):
        config_mod.load(config_path=path, registry_root_override=tmp_path)

    # And the declared value is used verbatim when it *is* declared.
    path = _write_config(tmp_path, {"org": "onemorerabbit"})
    cfg = config_mod.load(config_path=path, registry_root_override=tmp_path)
    assert cfg.ghcr_org == "onemorerabbit"


def test_every_compose_template_parameterises_the_namespace(cfg):
    """No compose template may hard-code a namespace.

    `compose.py` passes `ghcr_org` into the render context, so a template that
    writes a literal instead would bake one namespace into every deployed
    agent — the path by which a wrong default reaches production. Checks the
    shape (`ghcr.io/<anything>`), not a particular value, so it catches a
    hard-coded namespace whichever one someone picks.
    """
    literal = re.compile(r"ghcr\.io/(?!\{\{)")
    templates = sorted(Path("templates").rglob("compose.yml.j2"))
    assert templates, "no compose templates found — the guard would pass vacuously"
    offenders = [
        str(t) for t in templates if literal.search(t.read_text())
    ]
    assert not offenders, f"compose template hard-codes a namespace: {offenders}"
