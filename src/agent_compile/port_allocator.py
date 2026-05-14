"""Per-host port allocation for compose.yml ``ports:`` mapping.

Each agent on a host needs a unique local port for ``/healthz``. We:

1. Hash the agent name into the configured range (default 28789-28999).
2. Check the persisted endpoints file for collisions on the same host.
3. Increment until free; raise if range exhausted.
4. Persist the (host, agent, port) tuple back to the endpoints file.

Idempotency: an agent that already has a port allocated on its current host
keeps that port across re-compiles. Switching the agent's host triggers a
new allocation (the old entry is overwritten on save).

The endpoints file is guarded by a simple cross-platform file lock (a
sentinel ``.lock`` file created with ``O_EXCL``) so that parallel compiles
can't race the read-decide-write cycle.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from ruamel.yaml import YAML

from .config import Config


class PortAllocatorError(Exception):
    pass


@dataclass
class Allocation:
    host: str
    local_port: int


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


@contextlib.contextmanager
def _file_lock(path: Path, timeout: float = 5.0) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() - start > timeout:
                raise PortAllocatorError(
                    f"could not acquire lock on {lock_path} within {timeout}s"
                )
            time.sleep(0.05)
    try:
        os.close(fd)
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _hash_to_range(name: str, lo: int, hi: int) -> int:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    val = int.from_bytes(digest[:8], "big")
    return lo + (val % (hi - lo + 1))


def _load(path: Path) -> dict:
    if not path.is_file():
        return {"agents": {}}
    y = _yaml()
    with path.open(encoding="utf-8") as f:
        data = y.load(f) or {}
    if "agents" not in data or data["agents"] is None:
        data["agents"] = {}
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    y = _yaml()
    buf = io.StringIO()
    y.dump(data, buf)
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    os.replace(tmp, path)


def allocate(
    cfg: Config,
    flavour: str,
    agent_name: str,
    host: str,
) -> Allocation:
    """Allocate (or reuse) a port for ``agent_name`` on ``host``.

    Locks the flavour's endpoints file for the duration of read-decide-write.
    """
    flav = cfg.flavour(flavour)
    path = cfg.flavour_endpoints_path(flavour)
    with _file_lock(path):
        data = _load(path)
        agents = data["agents"]

        existing = agents.get(agent_name) or {}
        if (
            existing.get("host") == host
            and isinstance(existing.get("local_port"), int)
            and flav.port_range_low
            <= existing["local_port"]
            <= flav.port_range_high
        ):
            return Allocation(host=host, local_port=int(existing["local_port"]))

        occupied = {
            int(entry["local_port"])
            for name, entry in agents.items()
            if name != agent_name
            and isinstance(entry, dict)
            and entry.get("host") == host
            and isinstance(entry.get("local_port"), int)
        }
        seed = _hash_to_range(agent_name, flav.port_range_low, flav.port_range_high)
        span = flav.port_range_high - flav.port_range_low + 1
        candidate = seed
        for _ in range(span):
            if candidate not in occupied:
                agents[agent_name] = {"host": host, "local_port": candidate}
                _save(path, data)
                return Allocation(host=host, local_port=candidate)
            candidate = flav.port_range_low + (
                (candidate + 1 - flav.port_range_low) % span
            )
        raise PortAllocatorError(
            f"port range {flav.port_range_low}-{flav.port_range_high} "
            f"exhausted for flavour {flavour!r} on host {host!r}"
        )


def lookup(cfg: Config, flavour: str, agent_name: str) -> Optional[Allocation]:
    """Read-only view: return the allocation if one exists; ``None`` otherwise."""
    path = cfg.flavour_endpoints_path(flavour)
    if not path.is_file():
        return None
    data = _load(path)
    entry = (data.get("agents") or {}).get(agent_name)
    if not isinstance(entry, dict):
        return None
    if "host" not in entry or "local_port" not in entry:
        return None
    return Allocation(host=str(entry["host"]), local_port=int(entry["local_port"]))
