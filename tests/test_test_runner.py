"""Tests for the test runner — the compile-and-stub-prep portion.

The actual Docker spin-up is mocked. A separate integration test (gated on
``docker_cli.docker_available()``) would exercise the real path.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List

import pytest

from agent_compile import compile as compile_mod
from agent_compile import docker_cli
from agent_compile import test_runner as test_runner_mod


@dataclass
class FakeCompleted:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def test_stub_agent_shape():
    import os

    stub = compile_mod.stub_agent_for_template(
        template_id_str="openclaw:marketing_arc:v1",
        image_ref_str="openclaw:2026.5.5-r1",
        test_uuid="abc12345",
    )
    assert stub["app"]["template"] == "openclaw:marketing_arc:v1"
    assert stub["app"]["image"] == "openclaw:2026.5.5-r1"
    # Defaults to the invoking operator's uid/gid (mirrors image-compile's
    # probe) so the host-created test surfaces are writable by the container;
    # 1002 fallback where the platform has no getuid (Windows dev machine).
    # Brief: agent-compile-test-stub-uid v0.1.
    expected_uid = os.getuid() if hasattr(os, "getuid") else 1002
    expected_gid = os.getgid() if hasattr(os, "getgid") else 1002
    assert stub["local_user"]["uid"] == expected_uid
    assert stub["local_user"]["primary_gid"] == expected_gid
    assert stub["app"]["channels"] == {}
    assert stub["share_class"]["org"] == "arc"
    assert stub["name"].startswith("test_openclaw_marketing_arc_v1_")


def test_stub_agent_uid_overridable():
    stub = compile_mod.stub_agent_for_template(
        template_id_str="openclaw:marketing_arc:v1",
        image_ref_str="openclaw:2026.5.5-r1",
        test_uuid="abc12345",
        stub_uid=11042,
        stub_gid=11042,
    )
    assert stub["local_user"]["uid"] == 11042
    assert stub["local_user"]["primary_gid"] == 11042


def test_template_test_runs_against_preferred_image(cfg, monkeypatch):
    """Mock the Docker subprocess so the runner reports green without actually starting a container."""
    calls: List[List[str]] = []

    def fake_run(args, *, check=True, timeout=None):
        calls.append(list(args))
        if args and args[0] == "logs":
            return FakeCompleted(stdout="ok", stderr="")
        return FakeCompleted()

    monkeypatch.setattr(docker_cli, "docker_available", lambda: True)
    monkeypatch.setattr(docker_cli, "run", fake_run)

    class FakeResp:
        def __init__(self, status):
            self.status_code = status

    monkeypatch.setattr(
        "agent_compile.test_runner.requests.get",
        lambda url, timeout=2: FakeResp(200),
    )

    result = test_runner_mod.run_template_test(
        cfg, template_id_str="openclaw:marketing_arc:v1", timeout_seconds=5
    )
    assert result.success
    assert result.readyz_status == 200
    # First docker call must be `pull`; later one of `run` and `stop`
    call_verbs = [c[0] for c in calls if c]
    assert "pull" in call_verbs
    assert "run" in call_verbs


def test_template_test_reports_failure_when_readyz_never_green(cfg, monkeypatch):
    def fake_run(args, *, check=True, timeout=None):
        return FakeCompleted()

    monkeypatch.setattr(docker_cli, "docker_available", lambda: True)
    monkeypatch.setattr(docker_cli, "run", fake_run)

    class FakeResp:
        status_code = 503

    monkeypatch.setattr(
        "agent_compile.test_runner.requests.get",
        lambda url, timeout=2: FakeResp(),
    )
    # Avoid the polling loop wasting wall-clock seconds
    monkeypatch.setattr("agent_compile.test_runner.time.sleep", lambda s: None)

    result = test_runner_mod.run_template_test(
        cfg, template_id_str="openclaw:marketing_arc:v1", timeout_seconds=1
    )
    assert not result.success
    assert result.readyz_status == 503


def test_template_test_without_preferred_image_requires_against_image(cfg):
    """If a template lacks preferred_image and no --against-image, runner errors out."""
    # Replace preferred_image with empty
    from agent_compile import registry as registry_mod

    tpl = registry_mod.load_template(cfg, "openclaw", "marketing_arc", 1)
    tpl.preferred_image = None
    registry_mod.save_template(cfg, tpl, allow_overwrite=True)

    with pytest.raises(test_runner_mod.TestRunnerError, match="preferred_image"):
        test_runner_mod.run_template_test(
            cfg, template_id_str="openclaw:marketing_arc:v1"
        )


def test_template_test_no_docker_errors(cfg, monkeypatch):
    """If docker isn't on PATH, the runner refuses to proceed."""
    monkeypatch.setattr(docker_cli, "docker_available", lambda: False)
    with pytest.raises(test_runner_mod.TestRunnerError, match="docker not on PATH"):
        test_runner_mod.run_template_test(
            cfg, template_id_str="openclaw:marketing_arc:v1"
        )
