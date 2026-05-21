"""Instance compilation pipeline.

Loads an agent entry, resolves the template chain, applies instance-specific
overrides, builds the secret manifest, and emits artifacts to
``~/registry/.compiled/agents/<agent>/``.

Vault access is out of scope. The platform's apply playbook reads the
manifest and renders ``secrets.env`` on the agent host.
"""

from __future__ import annotations

import json
import os
import shutil
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from . import agent_entry
from . import compose as compose_mod
from . import matrix as matrix_mod
from . import merge as merge_mod
from . import registry as registry_mod
from . import resolver as resolver_mod
from . import secrets as secrets_mod
from .config import Config
from .identifiers import (
    IdentifierError,
    parse_image_ref,
    parse_template_id,
)


class CompileError(Exception):
    pass


class FlavourMismatchError(CompileError):
    pass


class MatrixBrokenError(CompileError):
    pass


class MatrixExperimentalWarning(UserWarning):
    pass


class UnconfiguredTemplateWarning(UserWarning):
    """The leaf template has entirely empty overrides — not a configured agent."""


@dataclass
class CompileResult:
    agent_name: str
    flavour: str
    image_version: str
    artifact_root: Path
    files: List[Path] = field(default_factory=list)


# --- public -----------------------------------------------------------------


def compile_agent(
    cfg: Config,
    agent_name: str,
    *,
    allow_experimental: bool = False,
) -> CompileResult:
    """Compile one registered agent. Reads from registry; writes to ``.compiled/agents/<agent>/``."""
    agent = registry_mod.get_agent(cfg, agent_name)
    return compile_pipeline(
        cfg,
        agent,
        allow_experimental=allow_experimental,
        artifact_root_override=None,
        emit_compose=True,
    )


def compile_pipeline(
    cfg: Config,
    agent: Dict[str, Any],
    *,
    allow_experimental: bool = False,
    artifact_root_override: Optional[Path] = None,
    emit_compose: bool = True,
) -> CompileResult:
    """Core compile pipeline. Operates on an agent *dict* — registry lookup is the caller's job.

    ``artifact_root_override`` is used by ``template test`` and ``compile test``
    to redirect artifact emission to a temp dir without touching ``.compiled/``.

    ``emit_compose=False`` skips compose.yml + port allocation. Useful for
    template-mode tests where we don't need a runnable compose stack.
    """
    agent_name = agent["name"]

    try:
        template_id = parse_template_id(agent_entry.app_template(agent))
        image_ref = parse_image_ref(agent_entry.app_image(agent))
        agent_entry.agent_org(agent)  # validate share_class.org present up front
    except (IdentifierError, agent_entry.AgentEntryError, KeyError) as e:
        raise CompileError(f"agent {agent_name}: {e}") from e
    if template_id.flavour != image_ref.flavour:
        raise FlavourMismatchError(
            f"agent {agent_name}: template flavour {template_id.flavour!r} "
            f"!= image flavour {image_ref.flavour!r}"
        )
    flavour = template_id.flavour

    matrix_entries = matrix_mod.load(cfg.matrix_path())
    matrix_template_field = f"{template_id.name}:v{template_id.version}"
    entry = matrix_mod.find(
        matrix_entries, flavour, image_ref.image_version, matrix_template_field
    )
    if entry is not None:
        if entry.status == "broken":
            raise MatrixBrokenError(
                f"matrix entry is broken: ({flavour}, {image_ref.image_version}, "
                f"{matrix_template_field}) — refusing to compile"
            )
        if entry.status == "experimental" and not allow_experimental:
            warnings.warn(
                f"matrix entry is experimental: ({flavour}, "
                f"{image_ref.image_version}, {matrix_template_field})",
                MatrixExperimentalWarning,
            )

    _warn_if_unconfigured(cfg, template_id)

    resolved = resolver_mod.resolve(cfg, template_id)

    flavour_json = _apply_instance_overrides(cfg, resolved.flavour_json, agent)

    secret_manifest = secrets_mod.derive_secret_manifest(
        flavour_json=flavour_json,
        template_manifest=resolved.secret_manifest,
        agent_name=agent_name,
    )

    flav_cfg = cfg.flavour(flavour)
    artifact_root = artifact_root_override or cfg.compiled_agent_path(agent_name)

    compose_yml: Optional[str] = None
    if emit_compose:
        compose_yml = compose_mod.render(
            cfg,
            flavour=flavour,
            image_version=image_ref.image_version,
            agent=agent,
        )

    files = _emit_artifacts(
        cfg,
        artifact_root,
        flavour_json_filename=flav_cfg.config_filename,
        flavour_json=flavour_json,
        workspace=resolved.workspace,
        skills=resolved.skills,
        secret_manifest=secret_manifest,
        agent=agent,
        compose_yml=compose_yml,
    )

    return CompileResult(
        agent_name=agent_name,
        flavour=flavour,
        image_version=image_ref.image_version,
        artifact_root=artifact_root,
        files=files,
    )


def stub_agent_for_template(
    *,
    template_id_str: str,
    image_ref_str: str,
    test_uuid: str,
    stub_uid: int = 65534,
    stub_gid: int = 65534,
    org: str = "arc",
    host: str = "otter",
) -> Dict[str, Any]:
    """Build an in-memory agent dict (live v0.4 + app-block shape) for ``template test``.

    Stub UID/GID match image-compile's probe (65534/65534 — nobody).
    """
    from .identifiers import parse_template_id as _parse_tid

    tid = _parse_tid(template_id_str)
    name = f"test_{tid.flavour}_{tid.name}_v{tid.version}_{test_uuid}"
    return {
        "name": name,
        "share_class": {
            "org": org,
            "grade": 0,
            "vertical": "any",
            "scope": "global",
        },
        "local_user": {"uid": stub_uid, "primary_gid": stub_gid},
        "cert": {"issue": True, "validity_days": 365},
        "host": host,
        "app": {
            "template": template_id_str,
            "image": image_ref_str,
            "channels": {},
        },
    }


def _warn_if_unconfigured(cfg: Config, template_id) -> None:
    """Warn if the leaf template has entirely empty overrides.

    An unconfigured template — typically `template new` with no follow-up
    `template edit` — resolves to just the image-defaults baseline, which is
    not a runnable agent (openclaw rejects it at boot). Advisory only;
    compile still proceeds.
    """
    try:
        tpl = registry_mod.load_template(
            cfg, template_id.flavour, template_id.name, template_id.version
        )
    except registry_mod.RegistryError:
        return
    overrides = tpl.overrides or {}
    if not (
        overrides.get("openclaw_json")
        or overrides.get("workspace")
        or overrides.get("skills")
    ):
        warnings.warn(
            f"template {template_id} has empty overrides — it adds nothing to "
            f"the image-defaults baseline and boots only a bare openclaw "
            f"gateway (default model, no persona, no channels, no skills). "
            f"Configure it with `agent-compile template edit {template_id}` — "
            f"or boot it, configure interactively via the openclaw CLI, and "
            f"`template snapshot` the result back — before treating it as a "
            f"real agent.",
            UnconfiguredTemplateWarning,
        )


# --- instance overrides -----------------------------------------------------


def _apply_instance_overrides(
    cfg: Config, flavour_json: Dict[str, Any], agent: Dict[str, Any]
) -> Dict[str, Any]:
    """Build a delta dict from the agent's registry entry and merge it in."""
    delta: Dict[str, Any] = {}

    # agent.name — merge ONLY into an `agent` block the template already
    # configures. agent-compile never creates a bare `agent: {name}` block:
    # openclaw rejects a name-without-model `agent` block ("Missing config",
    # exit 78), whereas a config with no `agent` block boots on openclaw's
    # default model. The container always carries AGENT_NAME in its env
    # (compose) regardless. Same gate as dprox below.
    if "agent" in flavour_json:
        delta["agent"] = {"name": agent.get("name", "")}

    reg_channels = agent_entry.app_channels(agent)
    if reg_channels:
        channels: Dict[str, Any] = {}
        for ch_name, ch_block in reg_channels.items():
            ch_block = ch_block or {}
            ch_delta: Dict[str, Any] = {}
            for key in ("bot_name", "handle"):
                if key in ch_block:
                    ch_delta[key] = ch_block[key]
            if "allowFrom" in ch_block:
                ch_delta["allowFrom"] = list(ch_block["allowFrom"])
            if ch_delta:
                channels[ch_name] = ch_delta
        if channels:
            delta["channels"] = channels

    # Fill dprox.endpoint ONLY when the resolved config already configures
    # dprox (the template — or bundle — has a `dprox` block). agent-compile
    # never invents a dprox block: a partial one (endpoint, no cert paths) is
    # an invalid openclaw config. Build brief: resolve the endpoint "if the
    # template's openclaw.json refers to it".
    if "dprox" in flavour_json:
        endpoint = _lookup_dprox_endpoint(cfg, agent_entry.agent_org(agent))
        if endpoint:
            delta["dprox"] = {"endpoint": endpoint}

    return merge_mod.merge_json(flavour_json, delta)


def _lookup_dprox_endpoint(cfg: Config, org: str) -> Optional[str]:
    """Resolve an org's dprox endpoint URL from `.compiled/dprox_endpoints.yml`.

    File format: docs/contracts/dprox-endpoints-file-v0_1.md. Each
    `endpoints.<org>` is either a block with a `url` key (preferred) or a
    bare URL string (tolerated). Missing file / org → None + warning.
    """
    path = cfg.dprox_endpoints_path()
    if not path.is_file():
        warnings.warn(
            f"dprox_endpoints.yml not found at {path}; dprox.endpoint left "
            "unresolved (dprox apply playbook produces this file — see "
            "docs/contracts/dprox-endpoints-file-v0_1.md)"
        )
        return None
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entry = (data.get("endpoints") or {}).get(org)
    if entry is None:
        return None
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("url")
    return None


# --- artifact emission ------------------------------------------------------


def _emit_artifacts(
    cfg: Config,
    artifact_root: Path,
    *,
    flavour_json_filename: str,
    flavour_json: Dict[str, Any],
    workspace: Dict[str, str],
    skills: List[str],
    secret_manifest: List[Dict[str, Any]],
    agent: Dict[str, Any],
    compose_yml: Optional[str],
) -> List[Path]:
    artifact_root.mkdir(parents=True, exist_ok=True)
    files: List[Path] = []

    p = artifact_root / flavour_json_filename
    _atomic_write_text(p, json.dumps(flavour_json, sort_keys=True, indent=2) + "\n")
    files.append(p)

    p = artifact_root / "secrets.manifest"
    _atomic_write_text(
        p, yaml.safe_dump({"secrets": secret_manifest}, sort_keys=False)
    )
    files.append(p)

    ws_dir = artifact_root / "workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    for name, content in workspace.items():
        p = ws_dir / name
        _atomic_write_text(p, content)
        files.append(p)

    skills_dir = ws_dir / "skills"
    if skills_dir.exists():
        for child in skills_dir.iterdir():
            if child.is_dir() and child.name not in skills:
                shutil.rmtree(child)
    if skills:
        skills_dir.mkdir(parents=True, exist_ok=True)
    for skill_name in skills:
        src = cfg.skill_path(skill_name)
        if not src.is_file():
            raise CompileError(
                f"skill body not found in library: {src} (skill={skill_name!r})"
            )
        dest_dir = skills_dir / skill_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "SKILL.md"
        _atomic_write_text(dest, src.read_text(encoding="utf-8"))
        files.append(dest)

    p = artifact_root / "cert-request.yml"
    cert_request = {
        "cn": agent["name"],
        "sans": [
            f"openclaw_{agent['name']}",
            f"openclaw_{agent['name']}_net",
        ],
        "key_type": "ed25519",
        "validity_days": agent_entry.cert_validity_days(agent),
        "purpose": "client_auth",
        "notes": f"Agent {agent['name']} -> dprox mTLS",
    }
    _atomic_write_text(p, yaml.safe_dump(cert_request, sort_keys=False))
    files.append(p)

    if compose_yml is not None:
        p = artifact_root / "compose.yml"
        _atomic_write_text(p, compose_yml)
        files.append(p)

    return files


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
