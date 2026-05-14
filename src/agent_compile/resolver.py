"""Template chain resolution.

Walks from a leaf ``TemplateID`` up through parents to an ``ImageDefaultsRef``
root, then applies overrides root-to-leaf using ``merge.py`` rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from . import merge as merge_mod
from . import registry as registry_mod
from .config import Config
from .identifiers import ImageDefaultsRef, TemplateID, parse


class ResolverError(Exception):
    pass


class CycleError(ResolverError):
    pass


class FlavourMismatchError(ResolverError):
    pass


@dataclass
class ResolvedTemplate:
    flavour: str
    image_version: str
    flavour_json: Dict[str, Any]
    workspace: Dict[str, str]
    skills: List[str]
    secret_manifest: List[str]
    from_chain: List[str]
    resolved_at: str = field(default_factory=lambda: "")


def walk_chain(
    cfg: Config, leaf: TemplateID
) -> Tuple[ImageDefaultsRef, List[registry_mod.Template]]:
    """Walk leaf → root. Returns ``(image_defaults_ref, [t_root_chain, ..., t_leaf])``.

    Detects cycles (raises ``CycleError``). Rejects cross-flavour parents
    (raises ``FlavourMismatchError``).
    """
    visited: List[str] = []
    chain: List[registry_mod.Template] = []
    current_id: str = str(leaf)

    while True:
        if current_id in visited:
            cycle_path = " -> ".join(visited + [current_id])
            raise CycleError(f"template chain cycle detected: {cycle_path}")
        visited.append(current_id)

        parsed = parse(current_id)
        if not isinstance(parsed, TemplateID):
            raise ResolverError(
                f"expected template ID in chain, got {type(parsed).__name__}: {current_id!r}"
            )
        if parsed.flavour != leaf.flavour:
            raise FlavourMismatchError(
                f"cross-flavour parent rejected: leaf flavour {leaf.flavour!r}, "
                f"chain reference {parsed.flavour!r} ({current_id})"
            )

        tpl = registry_mod.load_template(
            cfg, parsed.flavour, parsed.name, parsed.version
        )
        chain.append(tpl)

        parent_parsed = parse(tpl.parent)
        if isinstance(parent_parsed, ImageDefaultsRef):
            if parent_parsed.flavour != leaf.flavour:
                raise FlavourMismatchError(
                    f"cross-flavour image_defaults parent: leaf flavour {leaf.flavour!r}, "
                    f"image_defaults flavour {parent_parsed.flavour!r}"
                )
            chain.reverse()
            return parent_parsed, chain
        if isinstance(parent_parsed, TemplateID):
            current_id = str(parent_parsed)
            continue
        raise ResolverError(
            f"invalid parent reference in {tpl.id}: {tpl.parent!r}"
        )


def resolve(cfg: Config, leaf: TemplateID) -> ResolvedTemplate:
    """Resolve a leaf template's chain into concrete files."""
    root_ref, chain = walk_chain(cfg, leaf)
    bundle = registry_mod.load_image_defaults(
        cfg, root_ref.flavour, root_ref.image_version
    )

    flavour_json: Dict[str, Any] = merge_mod.merge_json(bundle.flavour_json, {})
    workspace: Dict[str, str] = dict(bundle.workspace)
    skills: List[str] = []
    secret_manifest: List[str] = []
    chain_ids: List[str] = [str(root_ref)]

    for tpl in chain:
        ov = tpl.overrides or {}
        flavour_json = merge_mod.merge_json(
            flavour_json, ov.get("openclaw_json") or {}
        )
        workspace = merge_mod.merge_workspace(workspace, ov.get("workspace") or {})
        skills = merge_mod.merge_skills(skills, ov.get("skills") or {})
        for s in tpl.secret_manifest or []:
            if s not in secret_manifest:
                secret_manifest.append(s)
        chain_ids.append(tpl.id)

    # leaf preferred_image takes precedence over the root's image
    leaf_tpl = chain[-1]
    if leaf_tpl.preferred_image:
        # preferred_image is "<flavour>:<image_version>"
        image_version = leaf_tpl.preferred_image.split(":", 1)[1]
    else:
        image_version = root_ref.image_version

    return ResolvedTemplate(
        flavour=leaf.flavour,
        image_version=image_version,
        flavour_json=flavour_json,
        workspace=workspace,
        skills=skills,
        secret_manifest=secret_manifest,
        from_chain=chain_ids,
        resolved_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
