"""Values that govern behaviour are declared, or the tool fails.

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


# --- constitution §11, generalised 2026-09-13 -------------------------------
#
# Every key below is declared in the shipped config.yml, so each default was
# dead unless a declaration went missing — which is exactly when it fired and
# exactly when nobody had chosen it. None qualifies as dprox's legitimate
# tunable ("a default whose wrong value is visible, or fails safe"): every one
# produces a plausible, readable, wrong result. `registry.root` is the sharpest
# — it defaulted to a real production path, so a dropped `registry:` block did
# not fail, it compiled and emitted against the live tree.

REQUIRED_KEYS = [
    ("registry", "root"),
    ("registry", "archive_root"),
    ("paths", "templates_dir"),
    ("paths", "image_defaults_dir"),
    ("paths", "agent_registry_file"),
    ("paths", "compatibility_matrix_file"),
    ("paths", "compiled_root"),
    ("paths", "skills_library_dir"),
    ("paths", "dprox_endpoints_file"),
    ("paths", "org_routing_file"),
    ("bless", "recency_window_days"),
    ("ghcr", "org"),
]


@pytest.mark.parametrize("section,key", REQUIRED_KEYS, ids=lambda v: str(v))
def test_absent_key_is_an_error_not_a_default(tmp_path, section, key):
    """Dropping any declared key fails at load, naming the key and the file."""
    raw = yaml.safe_load(config_mod._default_config_path().read_text())
    del raw[section][key]
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))

    with pytest.raises(ValueError) as e:
        config_mod.load(config_path=path)
    msg = str(e.value)
    assert key in msg, f"error does not name the missing key: {msg}"
    assert str(path) in msg, f"error does not name the config file: {msg}"


def test_shipped_config_declares_every_required_key():
    """The guard above is only meaningful if the real config declares them all."""
    raw = yaml.safe_load(config_mod._default_config_path().read_text())
    missing = [
        f"{sec}.{k}" for sec, k in REQUIRED_KEYS
        if not (raw.get(sec) or {}).get(k)
    ]
    assert not missing, f"config.yml is missing declared keys: {missing}"


def test_loader_reintroduces_no_silent_default():
    """No `.get("key", <literal>)` may creep back into the loader.

    Catches the pattern rather than any particular key, so a future config
    addition cannot quietly reintroduce §11's defect. Two-arg `.get` with an
    empty container default is fine — that is a missing *section*, whose keys
    are then checked individually.
    """
    src = Path(config_mod.__file__).read_text()
    offenders = [
        m.group(0)
        for m in re.finditer(r'\.get\(\s*"[^"]+"\s*,\s*(?!\{\}|\[\]|None)\S', src)
    ]
    assert not offenders, f"silent default reintroduced in config.py: {offenders}"
