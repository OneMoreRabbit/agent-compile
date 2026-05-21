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
    archive_root: Path
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
    ghcr_org: str = "arcpower"
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
        else Path(str(registry.get("root", "~/registry"))).expanduser()
    )
    archive_root = Path(
        str(registry.get("archive_root", "~/registry/.archive"))
    ).expanduser()

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

    ghcr_block = raw.get("ghcr", {}) or {}
    ghcr_org = str(ghcr_block.get("org", "arcpower"))

    return Config(
        registry_root=registry_root,
        archive_root=archive_root,
        templates_dir=paths.get("templates_dir", "agent_templates"),
        image_defaults_dir=paths.get("image_defaults_dir", "image_defaults"),
        agent_registry_file=paths.get("agent_registry_file", "agent_registry.yml"),
        compatibility_matrix_file=paths.get(
            "compatibility_matrix_file", "compatibility_matrix.yml"
        ),
        compiled_root=paths.get("compiled_root", ".compiled/agents"),
        skills_library_dir=paths.get("skills_library_dir", "skills"),
        dprox_endpoints_file=paths.get(
            "dprox_endpoints_file", ".compiled/dprox_endpoints.yml"
        ),
        org_routing_file=paths.get(
            "org_routing_file", "../inventory/group_vars/all/org_routing.yml"
        ),
        bless_recency_window_days=int(bless.get("recency_window_days", 30)),
        repo_root=repo_root,
        ghcr_org=ghcr_org,
        org_routing_path_override=org_routing_path_override,
        flavours=flavours,
        raw=raw,
    )
