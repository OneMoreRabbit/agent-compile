"""Template authoring operations: new and fork.

Higher-level orchestration on top of ``registry.py``.
(``snapshot`` lives in ``snapshot.py`` and lands in Pass 5.)
"""

from __future__ import annotations

import copy
from pathlib import Path

from . import registry as registry_mod
from .config import Config
from .identifiers import ImageDefaultsRef, TemplateID
from .matrix import now_iso


class TemplateOpsError(Exception):
    pass


def new_template(
    cfg: Config,
    new_id: TemplateID,
    from_image: ImageDefaultsRef,
    description: str = "",
) -> Path:
    """Create v1 of a new template with empty overrides.

    Parent is the image_defaults bundle. Bundle must exist on disk. New_id
    must not already exist. The new template's ``preferred_image`` mirrors
    the from_image so ``template test`` defaults to a coherent target.
    """
    if new_id.flavour != from_image.flavour:
        raise TemplateOpsError(
            f"flavour mismatch: new template flavour {new_id.flavour!r} "
            f"vs image-defaults flavour {from_image.flavour!r}"
        )
    if new_id.version != 1:
        raise TemplateOpsError(
            f"template new must create v1, got v{new_id.version}"
        )

    bundle_dir = cfg.image_defaults_path(from_image.flavour, from_image.image_version)
    if not bundle_dir.is_dir():
        raise TemplateOpsError(f"image_defaults bundle not found: {bundle_dir}")

    if registry_mod.template_exists(cfg, new_id.flavour, new_id.name, new_id.version):
        raise TemplateOpsError(f"template already exists: {new_id}")

    tpl = registry_mod.Template(
        flavour=new_id.flavour,
        name=new_id.name,
        version=new_id.version,
        parent=str(from_image),
        description=description,
        derived_from={
            "kind": "hand_authored",
            "source": "",
            "at": now_iso(),
        },
        overrides={
            "openclaw_json": {},
            "workspace": {},
            "skills": {},
        },
        secret_manifest=[],
        preferred_image=f"{from_image.flavour}:{from_image.image_version}",
    )
    return registry_mod.save_template(cfg, tpl)


def fork_template(
    cfg: Config,
    source_id: TemplateID,
    new_id: TemplateID,
    description: str = "",
) -> Path:
    """Create a new template by copying an existing template's overrides.

    The new template's ``parent`` is the source's parent (not the source
    itself) — forks branch off at the same point in the tree. New template
    starts at v1 under its new name.
    """
    if source_id.flavour != new_id.flavour:
        raise TemplateOpsError(
            f"cross-flavour fork rejected: source {source_id.flavour!r} "
            f"vs new {new_id.flavour!r}"
        )
    if new_id.version != 1:
        raise TemplateOpsError(
            f"template fork must create v1, got v{new_id.version}"
        )

    source = registry_mod.load_template(
        cfg, source_id.flavour, source_id.name, source_id.version
    )

    if registry_mod.template_exists(cfg, new_id.flavour, new_id.name, new_id.version):
        raise TemplateOpsError(f"template already exists: {new_id}")

    tpl = registry_mod.Template(
        flavour=new_id.flavour,
        name=new_id.name,
        version=new_id.version,
        parent=source.parent,
        description=description or f"Forked from {source.id}",
        derived_from={
            "kind": "fork",
            "source": source.id,
            "at": now_iso(),
        },
        overrides=copy.deepcopy(source.overrides),
        secret_manifest=list(source.secret_manifest),
        preferred_image=source.preferred_image,
    )
    return registry_mod.save_template(cfg, tpl)
