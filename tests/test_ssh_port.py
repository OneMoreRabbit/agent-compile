"""The ssh port in the compiled compose (ADR-0013 D6).

Allocated, never declared. A port is not a registry fact: a human chooses a
channel and no machine can derive it; nobody cares which port, only that it is
free. A registry-declared ssh port would be `local_user.supp_gids` again — a
hand-kept number a machine should allocate.
"""

from __future__ import annotations

import pytest
import yaml

from agent_compile import compile as compile_mod
from agent_compile import config as config_mod


AGENT = "agent_arc_marketing_bob"


def _grant_ssh(cfg):
    path = cfg.agent_registry_path()
    d = yaml.safe_load(path.read_text())
    next(a for a in d["agents"] if a["name"] == AGENT)["app"]["ssh"] = {}
    path.write_text(yaml.safe_dump(d))


def _published(cfg):
    compile_mod.compile_agent(cfg, AGENT, allow_experimental=True)
    text = (cfg.compiled_agent_path(AGENT) / "compose.yml").read_text()
    return [l.strip().lstrip("- ").strip('"') for l in text.splitlines() if "127.0.0.1" in l]


def test_no_grant_publishes_no_ssh_port(cfg):
    """Absence of `app.ssh` means nothing listens — one less door on the host."""
    ports = _published(cfg)
    assert len(ports) == 1, ports
    assert ports[0].endswith(":18789"), "only the gateway should be published"


def test_a_grant_publishes_ssh_on_loopback(cfg):
    """Published exactly like the gateway: host loopback, never 0.0.0.0."""
    _grant_ssh(cfg)
    ports = _published(cfg)
    assert len(ports) == 2, ports
    ssh = [p for p in ports if p.endswith(":22")]
    assert len(ssh) == 1, ports
    assert ssh[0].startswith("127.0.0.1:"), "ssh must not be published beyond loopback"


def test_the_ssh_port_comes_from_the_ssh_range(cfg):
    _grant_ssh(cfg)
    flav = cfg.flavour("openclaw")
    ssh = [p for p in _published(cfg) if p.endswith(":22")][0]
    port = int(ssh.split(":")[1])
    assert flav.ssh_port_range_low <= port <= flav.ssh_port_range_high


def test_both_ports_are_stable_across_recompiles(cfg):
    """Idempotent, like the gateway — a recompile must not renumber a live agent."""
    _grant_ssh(cfg)
    first = _published(cfg)
    second = _published(cfg)
    assert first == second, "ports moved on re-compile"


def test_gateway_and_ssh_ports_differ(cfg):
    _grant_ssh(cfg)
    ports = [int(p.split(":")[1]) for p in _published(cfg)]
    assert len(set(ports)) == 2, ports


def test_overlapping_ranges_fail_at_config_load(tmp_path):
    """Two ranges on one host must not overlap — fail closed at load.

    An ssh port colliding with a gateway port would publish one agent's shell
    where another's gateway is expected. The alternative to this check is a
    collision discovered by a deploy.
    """
    raw = yaml.safe_load(config_mod._default_config_path().read_text())
    raw["flavours"]["openclaw"]["ssh_port_range_low"] = 28900   # inside the gateway range
    raw["flavours"]["openclaw"]["ssh_port_range_high"] = 29100
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="overlaps"):
        config_mod.load(config_path=path, registry_root_override=tmp_path)


def test_inverted_ssh_range_fails_at_config_load(tmp_path):
    raw = yaml.safe_load(config_mod._default_config_path().read_text())
    raw["flavours"]["openclaw"]["ssh_port_range_low"] = 29999
    raw["flavours"]["openclaw"]["ssh_port_range_high"] = 29789
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="exceeds"):
        config_mod.load(config_path=path, registry_root_override=tmp_path)
