"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_compile import config as config_mod


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixture_registry(tmp_path: Path) -> Path:
    """Copy the fixture registry tree (image_defaults + agent_templates + agent_registry.yml)
    into ``tmp_path`` so tests can mutate it freely. Returns the registry root.
    """
    registry_root = tmp_path / "registry"
    registry_root.mkdir()
    for sub in ("image_defaults", "agent_templates", "skills"):
        src = FIXTURE_ROOT / sub
        if src.exists():
            shutil.copytree(src, registry_root / sub)
    for f in ("agent_registry.yml", "dprox_endpoints.yml", "org_routing.yml"):
        src = FIXTURE_ROOT / f
        if src.exists():
            shutil.copy(src, registry_root / f)
    return registry_root


@pytest.fixture
def cfg(fixture_registry: Path) -> config_mod.Config:
    # org_routing.yml lives outside the registry root in production
    # (inventory/, not registry/); for tests we drop it inside the tmp
    # registry and point config at it directly.
    return config_mod.load(
        registry_root_override=fixture_registry,
        org_routing_path_override=fixture_registry / "org_routing.yml",
    )
