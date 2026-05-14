"""Thin subprocess wrapper around the ``docker`` CLI.

Same pattern as image-compile's: call ``docker`` directly via ``subprocess``
rather than the Python Docker SDK. Simpler, less version coupling.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional


class DockerCliError(Exception):
    pass


def docker_available() -> bool:
    return shutil.which("docker") is not None


def run(args: List[str], *, check: bool = True, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    if not docker_available():
        raise DockerCliError("docker not on PATH")
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=timeout
    )
