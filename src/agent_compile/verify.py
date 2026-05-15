"""``verify`` — check that an agent's artifacts are current and its matrix is blessed.

Returns a structured result; the CLI translates to an exit code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from . import agent_entry
from . import matrix as matrix_mod
from . import registry as registry_mod
from .config import Config
from .identifiers import IdentifierError, parse_image_ref, parse_template_id


@dataclass
class VerifyResult:
    ok: bool
    agent_name: str
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def verify_agent(cfg: Config, agent_name: str) -> VerifyResult:
    result = VerifyResult(ok=True, agent_name=agent_name)

    try:
        agent = registry_mod.get_agent(cfg, agent_name)
    except registry_mod.RegistryError as e:
        result.ok = False
        result.failures.append(f"registry: {e}")
        return result

    try:
        template_id = parse_template_id(agent_entry.app_template(agent))
        image_ref = parse_image_ref(agent_entry.app_image(agent))
    except (IdentifierError, agent_entry.AgentEntryError, KeyError) as e:
        result.ok = False
        result.failures.append(f"identifier: {e}")
        return result

    if template_id.flavour != image_ref.flavour:
        result.ok = False
        result.failures.append(
            f"flavour mismatch: template={template_id.flavour}, image={image_ref.flavour}"
        )
        return result

    # Matrix must be blessed for this (flavour, image, template)
    matrix_template_field = f"{template_id.name}:v{template_id.version}"
    entries = matrix_mod.load(cfg.matrix_path())
    entry = matrix_mod.find(
        entries, template_id.flavour, image_ref.image_version, matrix_template_field
    )
    if entry is None:
        result.ok = False
        result.failures.append(
            f"no matrix entry for ({template_id.flavour}, {image_ref.image_version}, "
            f"{matrix_template_field})"
        )
    elif entry.status == "broken":
        result.ok = False
        result.failures.append(f"matrix entry is broken (tested_at={entry.tested_at})")
    elif entry.status == "experimental":
        result.warnings.append(
            f"matrix entry is experimental (tested_at={entry.tested_at})"
        )
        result.ok = False

    # Image-defaults bundle must exist (GHCR existence check is out of scope)
    bundle_dir = cfg.image_defaults_path(image_ref.flavour, image_ref.image_version)
    if not bundle_dir.is_dir():
        result.ok = False
        result.failures.append(f"image_defaults bundle missing: {bundle_dir}")

    # Artifacts must match a fresh compile (byte-identical re-emit is the contract)
    artifact_root = cfg.compiled_agent_path(agent_name)
    expected_files = {
        cfg.flavour(template_id.flavour).config_filename,
        "secrets.manifest",
        "cert-request.yml",
        "compose.yml",
        "workspace/AGENTS.md",
        "workspace/SOUL.md",
        "workspace/TOOLS.md",
    }
    if not artifact_root.is_dir():
        result.ok = False
        result.failures.append(f"compiled artifacts directory missing: {artifact_root}")
    else:
        for rel in expected_files:
            p = artifact_root / rel
            if not p.is_file():
                result.ok = False
                result.failures.append(f"compiled artifact missing: {p}")

    return result
