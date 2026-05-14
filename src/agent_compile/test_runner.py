"""Docker-backed test runner for ``template test`` and ``compile test``.

Spins up a container from a compiled stub-agent's artifacts, waits for the
flavour's ready endpoint, tears down. Returns a structured ``TestRunResult``.

Heavy integration code path. Unit tests mock out ``docker_cli.run``.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import yaml

from . import compile as compile_mod
from . import docker_cli
from .config import Config


class TestRunnerError(Exception):
    pass


@dataclass
class TestRunResult:
    success: bool
    test_uuid: str
    container_name: str
    duration_seconds: int
    readyz_status: Optional[int]
    artifact_root: Path
    container_logs: str = ""


def _free_localhost_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _write_stub_secrets_env(artifact_root: Path, target: Path) -> None:
    """Write a stub secrets.env at ``target`` covering every name in the manifest."""
    sm_path = artifact_root / "secrets.manifest"
    sm = yaml.safe_load(sm_path.read_text(encoding="utf-8")) or {}
    lines = [
        f"{entry['name']}=stub-not-real"
        for entry in (sm.get("secrets") or [])
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def run_template_test(
    cfg: Config,
    *,
    template_id_str: str,
    against_image_str: Optional[str] = None,
    timeout_seconds: int = 60,
) -> TestRunResult:
    """Build a stub agent for the template, compile, run, tear down.

    On green: caller (CLI handler) writes a matrix experimental entry.
    """
    from .identifiers import parse_template_id

    tid = parse_template_id(template_id_str)
    if against_image_str:
        image_ref_str = against_image_str
    else:
        from . import registry as registry_mod

        tpl = registry_mod.load_template(cfg, tid.flavour, tid.name, tid.version)
        if not tpl.preferred_image:
            raise TestRunnerError(
                f"template {template_id_str} has no preferred_image and "
                "--against-image was not supplied"
            )
        image_ref_str = tpl.preferred_image

    test_uuid = uuid.uuid4().hex[:8]
    stub_agent = compile_mod.stub_agent_for_template(
        template_id_str=template_id_str,
        image_ref_str=image_ref_str,
        test_uuid=test_uuid,
    )

    test_root = cfg.registry_root / ".test" / stub_agent["name"]
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True)

    artifact_root = test_root / "artifacts"
    result = compile_mod.compile_pipeline(
        cfg,
        stub_agent,
        allow_experimental=True,
        artifact_root_override=artifact_root,
        emit_compose=False,
    )

    return _run_container(
        cfg,
        flavour=result.flavour,
        image_version=result.image_version,
        artifact_root=artifact_root,
        test_uuid=test_uuid,
        stub_agent=stub_agent,
        timeout_seconds=timeout_seconds,
    )


def _run_container(
    cfg: Config,
    *,
    flavour: str,
    image_version: str,
    artifact_root: Path,
    test_uuid: str,
    stub_agent: Dict[str, Any],
    timeout_seconds: int,
) -> TestRunResult:
    if not docker_cli.docker_available():
        raise TestRunnerError(
            "docker not on PATH; install Docker or run with mocked test_runner"
        )

    flav_cfg = cfg.flavour(flavour)
    image_tag = f"ghcr.io/{cfg.ghcr_org}/{flav_cfg.image_line}:{image_version}"
    container_name = f"agent-compile-test-{test_uuid}"

    surfaces_root = artifact_root.parent / "surfaces"
    for surface in ("configs", "memory", "sessions", "scratch"):
        (surfaces_root / surface / "main").mkdir(parents=True, exist_ok=True)
    # Place flavour_json + workspace from the compiled artifacts
    shutil.copy(
        artifact_root / flav_cfg.config_filename,
        surfaces_root / "configs" / "main" / flav_cfg.config_filename,
    )
    if (artifact_root / "workspace").is_dir():
        shutil.copytree(
            artifact_root / "workspace",
            surfaces_root / "memory" / "main" / "workspace",
            dirs_exist_ok=True,
        )
    _write_stub_secrets_env(
        artifact_root, surfaces_root / "configs" / "main" / "secrets.env"
    )

    probe_port = _free_localhost_port()
    docker_cli.run(["pull", image_tag], check=False)

    run_args = [
        "run", "-d", "--rm",
        "--name", container_name,
        "-e", "AGENT_NAME=test",
        "-e", f"AGENT_UID={stub_agent['local_user']['uid']}",
        "-e", f"AGENT_PRIMARY_GID={stub_agent['local_user']['primary_gid']}",
        "-e", "AGENT_SUPP_GIDS=",
        "-e", "AGENT_HOME=/agent",
        "-e", "OPENCLAW_BIND=lan",
        "-e", f"OPENCLAW_PORT={flav_cfg.default_port}",
        "-v", f"{surfaces_root}/configs:/agent/configs",
        "-v", f"{surfaces_root}/memory:/agent/memory",
        "-v", f"{surfaces_root}/sessions:/agent/sessions",
        "-v", f"{surfaces_root}/scratch:/agent/scratch",
        "-p", f"127.0.0.1:{probe_port}:{flav_cfg.default_port}",
        image_tag,
    ]
    started = time.monotonic()
    try:
        docker_cli.run(run_args)
    except subprocess.CalledProcessError as e:
        raise TestRunnerError(f"docker run failed: {e.stderr}") from e

    readyz_status: Optional[int] = None
    success = False
    try:
        deadline = started + timeout_seconds
        ready_url = f"http://127.0.0.1:{probe_port}{flav_cfg.ready_endpoint}"
        while time.monotonic() < deadline:
            try:
                r = requests.get(ready_url, timeout=2)
                readyz_status = r.status_code
                if 200 <= r.status_code < 300:
                    success = True
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
    finally:
        logs = ""
        try:
            lp = docker_cli.run(["logs", container_name], check=False)
            logs = (lp.stdout or "") + (lp.stderr or "")
        except Exception:
            pass
        try:
            docker_cli.run(["stop", container_name], check=False)
        except Exception:
            pass

    return TestRunResult(
        success=success,
        test_uuid=test_uuid,
        container_name=container_name,
        duration_seconds=int(time.monotonic() - started),
        readyz_status=readyz_status,
        artifact_root=artifact_root,
        container_logs=logs,
    )
