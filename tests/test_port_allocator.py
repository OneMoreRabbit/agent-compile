"""Tests for the per-host port allocator."""

from __future__ import annotations

import pytest

from agent_compile import port_allocator


def test_allocates_deterministically_for_same_name(cfg):
    a = port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    cfg.flavour_endpoints_path("openclaw").unlink()
    b = port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    assert a.local_port == b.local_port


def test_port_within_configured_range(cfg):
    flav = cfg.flavour("openclaw")
    alloc = port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    assert flav.port_range_low <= alloc.local_port <= flav.port_range_high


def test_idempotent_reuses_existing_port(cfg):
    a = port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    b = port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    assert a.local_port == b.local_port


def test_collision_on_same_host_increments(cfg, monkeypatch):
    """Two agents that hash to the same seed must end up with different ports on the same host."""
    monkeypatch.setattr(
        port_allocator, "_hash_to_range", lambda name, lo, hi: lo
    )
    a = port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    b = port_allocator.allocate(cfg, "openclaw", "agent_b", "marten")
    assert a.local_port != b.local_port


def test_same_seed_on_different_hosts_allowed(cfg, monkeypatch):
    """Same port number is fine if the agents live on different hosts."""
    monkeypatch.setattr(
        port_allocator, "_hash_to_range", lambda name, lo, hi: lo
    )
    a = port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    b = port_allocator.allocate(cfg, "openclaw", "agent_b", "otter")
    assert a.local_port == b.local_port


def test_lookup_returns_none_when_unset(cfg):
    assert port_allocator.lookup(cfg, "openclaw", "agent_a") is None


def test_lookup_returns_allocation(cfg):
    port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    found = port_allocator.lookup(cfg, "openclaw", "agent_a")
    assert found is not None
    assert found.host == "marten"


def test_range_exhausted_raises(cfg, monkeypatch):
    """Force the configured range to size 1 and verify the second allocation on the same host fails."""
    flav = cfg.flavour("openclaw")
    monkeypatch.setattr(flav, "port_range_low", 28789)
    monkeypatch.setattr(flav, "port_range_high", 28789)
    port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    with pytest.raises(port_allocator.PortAllocatorError, match="exhausted"):
        port_allocator.allocate(cfg, "openclaw", "agent_b", "marten")


def test_host_change_reallocates(cfg):
    a = port_allocator.allocate(cfg, "openclaw", "agent_a", "marten")
    b = port_allocator.allocate(cfg, "openclaw", "agent_a", "otter")
    assert b.host == "otter"
    # Allocation may or may not change number; what matters is the host record updates.
    found = port_allocator.lookup(cfg, "openclaw", "agent_a")
    assert found is not None
    assert found.host == "otter"
