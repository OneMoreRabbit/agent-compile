"""Tool configuration loader.

Loads `config.yml` from the agent-compile repo root (or via the
``AGENT_COMPILE_CONFIG`` env var). Exposes typed accessors for derived paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass
class FlavourConfig:
    config_filename: str
    image_line: str
    health_endpoint: str
    ready_endpoint: str
    port_env_var: str
    default_port: int
    port_range_low: int
    port_range_high: int
    instance_fields_list: str
    endpoints_file: str


@dataclass
class Config:
    registry_root: Path
    templates_dir: str
    image_defaults_dir: str
    agent_registry_file: str
    compatibility_matrix_file: str
    compiled_root: str
    skills_library_dir: str
    dprox_endpoints_file: str
    org_routing_file: str
    bless_recency_window_days: int
    repo_root: Path
    ghcr_org: str
    org_routing_path_override: Optional[Path] = None
    flavours: Dict[str, FlavourConfig] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def template_root(self, flavour: str) -> Path:
        return self.registry_root / self.templates_dir / flavour

    def template_path(self, flavour: str, name: str, version: int) -> Path:
        return self.template_root(flavour) / name / f"v{version}.yml"

    def image_defaults_path(self, flavour: str, image_version: str) -> Path:
        return self.registry_root / self.image_defaults_dir / flavour / image_version

    def agent_registry_path(self) -> Path:
        return self.registry_root / self.agent_registry_file

    def matrix_path(self) -> Path:
        return self.registry_root / self.compatibility_matrix_file

    def compiled_agent_path(self, agent_name: str) -> Path:
        return self.registry_root / self.compiled_root / agent_name

    def skill_path(self, skill_name: str) -> Path:
        return self.registry_root / self.skills_library_dir / skill_name / "SKILL.md"

    def dprox_endpoints_path(self) -> Path:
        return self.registry_root / self.dprox_endpoints_file

    def org_routing_path(self) -> Path:
        """Path to ``org_routing.yml``.

        Lives outside the registry root (``inventory/`` vs ``registry/``).
        An explicit override (used by tests) wins; otherwise the configured
        ``org_routing_file`` is resolved — absolute as-is, relative against
        the registry root.
        """
        if self.org_routing_path_override is not None:
            return self.org_routing_path_override
        p = Path(self.org_routing_file).expanduser()
        if p.is_absolute():
            return p
        return (self.registry_root / p).resolve()

    def flavour(self, name: str) -> FlavourConfig:
        if name not in self.flavours:
            raise KeyError(f"flavour not configured: {name!r}")
        return self.flavours[name]

    def flavour_endpoints_path(self, flavour: str) -> Path:
        return self.registry_root / self.flavour(flavour).endpoints_file

    def flavour_templates_dir(self, flavour: str, image_version: str) -> Path:
        """Per-flavour, per-schema-version Jinja templates dir.

        ``image_version`` is the full ``<upstream>-r<rev>`` form; we strip
        the ``-r<rev>`` suffix and prefix ``v`` to derive the schema dir
        name (e.g. ``2026.5.5-r1`` -> ``v2026.5.5``).
        """
        schema = "v" + image_version.rsplit("-r", 1)[0]
        return self.repo_root / "templates" / flavour / schema


def _default_config_path() -> Path:
    env = os.environ.get("AGENT_COMPILE_CONFIG")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "config.yml"


def _required(block: dict, key: str, section: str, config_path: Path) -> Any:
    """A declared value, or an error. Never a plausible substitute.

    Constitution §11: a value that governs behaviour is declared, or the tool
    fails at startup. A silent default is a defect regardless of which value it
    holds — it takes effect with nobody choosing it, and a *plausible* default
    is worse than an absurd one because it is the kind nobody audits. Every
    value routed through here produces a readable, wrong result if guessed:
    a wrong registry root compiles and emits against the wrong tree.
    """
    value = block.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(
            f"{section}.{key} missing from {config_path} — it governs behaviour, "
            "so it is declared or this fails; there is deliberately no fallback "
            "(constitution §11)."
        )
    return value


def load(
    config_path: Optional[Path] = None,
    registry_root_override: Optional[Path] = None,
    org_routing_path_override: Optional[Path] = None,
) -> Config:
    """Load ``config.yml`` and return a typed ``Config``.

    ``registry_root_override`` (CLI ``--registry-root``) overrides the
    ``registry.root`` field for testing. ``org_routing_path_override``
    pins the org_routing file path directly (used by tests, where the
    inventory tree isn't reproduced).
    """
    if config_path is None:
        config_path = _default_config_path()
    if not config_path.is_file():
        raise FileNotFoundError(f"config file not found: {config_path}")
    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    repo_root = config_path.resolve().parent
    registry = raw.get("registry", {}) or {}
    paths = raw.get("paths", {}) or {}
    bless = raw.get("bless", {}) or {}
    flavours_raw = raw.get("flavours", {}) or {}

    registry_root = (
        registry_root_override
        if registry_root_override is not None
        else Path(str(_required(registry, "root", "registry", config_path))).expanduser()
    )

    flavours: Dict[str, FlavourConfig] = {}
    for fname, block in flavours_raw.items():
        try:
            flavours[fname] = FlavourConfig(
                config_filename=block["config_filename"],
                image_line=block["image_line"],
                health_endpoint=block["health_endpoint"],
                ready_endpoint=block["ready_endpoint"],
                port_env_var=block["port_env_var"],
                default_port=int(block["default_port"]),
                port_range_low=int(block["port_range_low"]),
                port_range_high=int(block["port_range_high"]),
                instance_fields_list=block["instance_fields_list"],
                endpoints_file=block["endpoints_file"],
            )
        except KeyError as e:
            raise ValueError(
                f"flavour {fname!r} in {config_path} missing required key {e.args[0]!r}"
            ) from e

    # A registry namespace is the sharpest case of §11: agent-compile writes it
    # into every compiled compose.yml and into what `template test` pulls, so an
    # invented one reaches production without any file being copied or read
    # (AgentEco GHCR ruling, 2026-09-13).
    ghcr_block = raw.get("ghcr", {}) or {}
    ghcr_org = str(_required(ghcr_block, "org", "ghcr", config_path)).strip()

    return Config(
        registry_root=registry_root,
        templates_dir=_required(paths, "templates_dir", "paths", config_path),
        image_defaults_dir=_required(paths, "image_defaults_dir", "paths", config_path),
        agent_registry_file=_required(paths, "agent_registry_file", "paths", config_path),
        compatibility_matrix_file=_required(paths, "compatibility_matrix_file", "paths", config_path),
        compiled_root=_required(paths, "compiled_root", "paths", config_path),
        skills_library_dir=_required(paths, "skills_library_dir", "paths", config_path),
        dprox_endpoints_file=_required(paths, "dprox_endpoints_file", "paths", config_path),
        org_routing_file=_required(paths, "org_routing_file", "paths", config_path),
        bless_recency_window_days=int(_required(bless, "recency_window_days", "bless", config_path)),
        repo_root=repo_root,
        ghcr_org=ghcr_org,
        org_routing_path_override=org_routing_path_override,
        flavours=flavours,
        raw=raw,
    )
