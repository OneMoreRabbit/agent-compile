"""Registry I/O: agent_registry.yml, agent_templates/, image_defaults/.

Read tolerance for image_defaults bundles per
``../../../docs/contracts/image-defaults-bundle-schema-v0_1.md`` —
required files error, unknown files warn.
"""

from __future__ import annotations

import io
import json
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from ruamel.yaml import YAML

from .config import Config


class RegistryError(Exception):
    pass


@dataclass
class ImageDefaultsBundle:
    flavour: str
    image_version: str
    flavour_json: Dict[str, Any]
    workspace: Dict[str, str]
    metadata: Dict[str, Any]
    probe_report: Optional[Dict[str, Any]] = None


@dataclass
class Template:
    flavour: str
    name: str
    version: int
    parent: str
    description: str
    derived_from: Dict[str, Any]
    overrides: Dict[str, Any]
    secret_manifest: List[str]
    preferred_image: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.flavour}:{self.name}:v{self.version}"


def _ruamel() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


# --- image_defaults bundle --------------------------------------------------


def load_image_defaults(
    cfg: Config, flavour: str, image_version: str
) -> ImageDefaultsBundle:
    """Read an image_defaults bundle from disk.

    Missing required files raise ``RegistryError``. Unknown extra files at the
    bundle root produce a ``warnings.warn`` and are ignored (forward-compat).
    """
    bundle_dir = cfg.image_defaults_path(flavour, image_version)
    if not bundle_dir.is_dir():
        raise RegistryError(
            f"image_defaults bundle not found: {bundle_dir} "
            f"(flavour={flavour}, image_version={image_version})"
        )

    try:
        flav = cfg.flavour(flavour)
    except KeyError as e:
        raise RegistryError(str(e)) from e

    flavour_json_path = bundle_dir / flav.config_filename
    if not flavour_json_path.is_file():
        raise RegistryError(f"missing required file in bundle: {flavour_json_path}")
    with flavour_json_path.open(encoding="utf-8") as f:
        flavour_json = json.load(f)

    workspace_dir = bundle_dir / "workspace"
    workspace: Dict[str, str] = {}
    for name in ("AGENTS.md", "SOUL.md", "TOOLS.md"):
        p = workspace_dir / name
        if not p.is_file():
            raise RegistryError(f"missing required workspace file in bundle: {p}")
        workspace[name] = p.read_text(encoding="utf-8")

    metadata_path = bundle_dir / "metadata.yml"
    if not metadata_path.is_file():
        raise RegistryError(f"missing required file in bundle: {metadata_path}")
    with metadata_path.open(encoding="utf-8") as f:
        metadata = yaml.safe_load(f) or {}

    probe_path = bundle_dir / "probe-report.yml"
    probe_report: Optional[Dict[str, Any]] = None
    if probe_path.is_file():
        with probe_path.open(encoding="utf-8") as f:
            probe_report = yaml.safe_load(f)
    else:
        warnings.warn(f"probe-report.yml missing from bundle: {bundle_dir}")

    # compose.yml.j2 is an optional bundle member: image-compile is proposed
    # to ship it per release (compose-template-in-bundle proposal). It is read
    # separately by compose._resolve_compose_template_dir, not here — listed so
    # a bundle that already carries one is not flagged as an unknown file.
    expected_at_root = {
        flav.config_filename,
        "metadata.yml",
        "probe-report.yml",
        "compose.yml.j2",
    }
    for child in bundle_dir.iterdir():
        if child.name in expected_at_root or child.name == "workspace":
            continue
        if child.name.startswith("."):
            continue
        warnings.warn(f"unknown file in image_defaults bundle (ignored): {child}")

    return ImageDefaultsBundle(
        flavour=flavour,
        image_version=image_version,
        flavour_json=flavour_json,
        workspace=workspace,
        metadata=metadata,
        probe_report=probe_report,
    )


# --- agent templates --------------------------------------------------------


def load_template(cfg: Config, flavour: str, name: str, version: int) -> Template:
    path = cfg.template_path(flavour, name, version)
    if not path.is_file():
        raise RegistryError(f"template not found: {path}")
    y = _ruamel()
    with path.open(encoding="utf-8") as f:
        raw = y.load(f) or {}
    return _template_from_mapping(raw, flavour, name, version, path)


def _template_from_mapping(
    raw: Dict[str, Any], flavour: str, name: str, version: int, source: Path
) -> Template:
    for required in ("name", "version", "flavour", "parent"):
        if required not in raw:
            raise RegistryError(
                f"template {source}: missing required field {required!r}"
            )
    if str(raw["flavour"]) != flavour:
        raise RegistryError(
            f"template {source}: flavour {raw['flavour']!r} does not match directory {flavour!r}"
        )
    if str(raw["name"]) != name:
        raise RegistryError(
            f"template {source}: name {raw['name']!r} does not match directory {name!r}"
        )
    if int(raw["version"]) != version:
        raise RegistryError(
            f"template {source}: version {raw['version']!r} does not match filename v{version}"
        )

    overrides = raw.get("overrides") or {}

    # Coerce ruamel CommentedMap/CommentedSeq into plain dict/list for downstream use
    def _plain(value):
        if hasattr(value, "items"):
            return {k: _plain(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_plain(v) for v in value]
        return value

    return Template(
        flavour=flavour,
        name=name,
        version=version,
        parent=str(raw["parent"]),
        description=str(raw.get("description") or ""),
        derived_from=_plain(raw.get("derived_from") or {}),
        overrides={
            "openclaw_json": _plain(overrides.get("openclaw_json") or {}),
            "workspace": _plain(overrides.get("workspace") or {}),
            "skills": _plain(overrides.get("skills") or {}),
        },
        secret_manifest=list(raw.get("secret_manifest") or []),
        preferred_image=(
            str(raw["preferred_image"]) if raw.get("preferred_image") else None
        ),
        raw=_plain(raw),
    )


def template_exists(cfg: Config, flavour: str, name: str, version: int) -> bool:
    return cfg.template_path(flavour, name, version).is_file()


def save_template(
    cfg: Config, template: Template, *, allow_overwrite: bool = False
) -> Path:
    path = cfg.template_path(template.flavour, template.name, template.version)
    if path.exists() and not allow_overwrite:
        raise RegistryError(f"template already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)

    data: Dict[str, Any] = {
        "name": template.name,
        "version": template.version,
        "flavour": template.flavour,
        "parent": template.parent,
        "description": template.description,
        "derived_from": template.derived_from,
        "overrides": template.overrides,
        "secret_manifest": template.secret_manifest,
        "preferred_image": template.preferred_image,
    }

    y = _ruamel()
    buf = io.StringIO()
    y.dump(data, buf)
    tmp = path.with_suffix(".yml.new")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    os.replace(tmp, path)
    return path


def list_templates(
    cfg: Config, flavour: Optional[str] = None
) -> Dict[str, Dict[str, List[int]]]:
    """Return ``{flavour: {template_name: [versions]}}`` sorted."""
    out: Dict[str, Dict[str, List[int]]] = {}
    root = cfg.registry_root / cfg.templates_dir
    if not root.is_dir():
        return out
    flavours = (
        [flavour]
        if flavour
        else sorted(p.name for p in root.iterdir() if p.is_dir())
    )
    for flav in flavours:
        flav_dir = root / flav
        if not flav_dir.is_dir():
            continue
        out[flav] = {}
        for name_dir in sorted(p for p in flav_dir.iterdir() if p.is_dir()):
            versions: List[int] = []
            for f in name_dir.iterdir():
                if f.is_file() and f.suffix == ".yml" and f.stem.startswith("v"):
                    try:
                        versions.append(int(f.stem[1:]))
                    except ValueError:
                        pass
            out[flav][name_dir.name] = sorted(versions)
    return out


# --- agent registry ---------------------------------------------------------


def load_agent_registry(cfg: Config) -> Dict[str, Any]:
    path = cfg.agent_registry_path()
    if not path.is_file():
        raise RegistryError(f"agent registry not found: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_agent(cfg: Config, agent_name: str) -> Dict[str, Any]:
    reg = load_agent_registry(cfg)
    for agent in reg.get("agents") or []:
        if agent.get("name") == agent_name:
            return agent
    raise RegistryError(f"agent not found in registry: {agent_name}")


# --- org routing ------------------------------------------------------------


def load_org_routing(cfg: Config) -> Dict[str, Any]:
    """Load the ``org_routing`` table.

    Returns ``{<org>: {fileserver, vector_host}}``. Empty dict if the file is
    absent — callers decide whether that's fatal.
    """
    path = cfg.org_routing_path()
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("org_routing") or {}
