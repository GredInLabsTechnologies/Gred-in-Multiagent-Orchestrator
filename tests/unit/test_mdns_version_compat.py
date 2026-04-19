"""BUGS_LATENTES §H11 — runtime_version compat check en discover.

El mDNS advertiser publicaba runtime_version en el TXT record, pero ningún
consumer lo usaba para gate. Ahora ``compute_compatibility()`` + campo
``DiscoveredPeer.compatibility_status`` exponen la compat para UI/CLI.

Semantics:
- major version idéntica → "compatible"
- major version diferente → "incompatible"
- version vacía o no parseable → "unknown"
- Advisory ONLY — no excluye peers ni cambia orden
"""
from __future__ import annotations

import pytest

from tools.gimo_server.services.mesh.mdns_discovery import (
    _parse_semver,
    compute_compatibility,
)


def test_parse_semver_basic():
    assert _parse_semver("0.1.0") == (0, 1, 0)
    assert _parse_semver("1.2.3") == (1, 2, 3)
    assert _parse_semver("2") == (2, 0, 0)
    assert _parse_semver("3.4") == (3, 4, 0)


def test_parse_semver_strips_prerelease():
    assert _parse_semver("1.2.3-rc1") == (1, 2, 3)
    assert _parse_semver("0.1.0-ci-42-android") == (0, 1, 0)


def test_parse_semver_strips_build_metadata():
    assert _parse_semver("1.0.0+build.42") == (1, 0, 0)


def test_parse_semver_invalid_returns_none():
    assert _parse_semver("") is None
    assert _parse_semver("not-a-version") is None
    assert _parse_semver("vNext") is None


def test_compute_compatibility_same_major():
    assert compute_compatibility("0.1.0", "0.2.5") == "compatible"
    assert compute_compatibility("1.0.0", "1.99.99") == "compatible"


def test_compute_compatibility_different_major():
    assert compute_compatibility("0.1.0", "1.0.0") == "incompatible"
    assert compute_compatibility("2.3.4", "3.0.0") == "incompatible"


def test_compute_compatibility_unknown_when_local_empty():
    assert compute_compatibility("", "0.1.0") == "unknown"


def test_compute_compatibility_unknown_when_remote_empty():
    assert compute_compatibility("0.1.0", "") == "unknown"


def test_compute_compatibility_unknown_when_unparseable():
    assert compute_compatibility("foo", "0.1.0") == "unknown"
    assert compute_compatibility("0.1.0", "bar") == "unknown"


def test_discovered_peer_has_compatibility_field_default_unknown():
    """DiscoveredPeer construido sin status explícito arranca como 'unknown'."""
    from tools.gimo_server.services.mesh.mdns_discovery import DiscoveredPeer
    p = DiscoveredPeer(name="x", host="1.2.3.4", port=9325, url="http://x:9325")
    assert p.compatibility_status == "unknown"


def test_discovered_peer_accepts_all_three_states():
    """Los 3 valores del enum son aceptados por el dataclass."""
    from tools.gimo_server.services.mesh.mdns_discovery import DiscoveredPeer
    for status in ("compatible", "incompatible", "unknown"):
        p = DiscoveredPeer(
            name="x", host="1.2.3.4", port=9325, url="http://x:9325",
            compatibility_status=status,
        )
        assert p.compatibility_status == status
