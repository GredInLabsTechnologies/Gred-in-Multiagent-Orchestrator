"""Guard: trusted Ed25519 public key está embedded + parseable.

Plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_CROSS_COMPILE §Change 5.

El MVP dejó ``EMBEDDED_RUNTIME_PUBLIC_KEY`` vacío para que el env var fuera la
única fuente. Este plan embedded un valor concreto — rotación requires new
release del Core. El test ancla que el valor está presente y es parseable
como Ed25519 SubjectPublicKeyInfo.
"""
from __future__ import annotations

import pytest


def test_embedded_public_key_is_not_empty() -> None:
    from tools.gimo_server.security.runtime_signature import (
        EMBEDDED_RUNTIME_PUBLIC_KEY,
    )
    assert EMBEDDED_RUNTIME_PUBLIC_KEY.strip(), (
        "EMBEDDED_RUNTIME_PUBLIC_KEY está vacío — el release oficial debe "
        "embedder la pubkey productiva (generada por scripts/generate_runtime_keys.py)."
    )


def test_embedded_public_key_is_valid_ed25519() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from tools.gimo_server.security.runtime_signature import (
        EMBEDDED_RUNTIME_PUBLIC_KEY,
    )
    pub = load_pem_public_key(EMBEDDED_RUNTIME_PUBLIC_KEY.encode("utf-8"))
    assert isinstance(pub, Ed25519PublicKey), (
        "EMBEDDED_RUNTIME_PUBLIC_KEY debe ser Ed25519 SubjectPublicKeyInfo."
    )


def test_get_runtime_public_key_returns_embedded_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("ORCH_RUNTIME_PUBLIC_KEY", raising=False)
    from tools.gimo_server.security.runtime_signature import (
        EMBEDDED_RUNTIME_PUBLIC_KEY,
        get_runtime_public_key_pem,
    )
    assert get_runtime_public_key_pem() == EMBEDDED_RUNTIME_PUBLIC_KEY


def test_env_override_wins_over_embedded(monkeypatch) -> None:
    override_body = "-----BEGIN PUBLIC KEY-----\nOVERRIDE\n-----END PUBLIC KEY-----"
    monkeypatch.setenv("ORCH_RUNTIME_PUBLIC_KEY", override_body)
    from tools.gimo_server.security.runtime_signature import get_runtime_public_key_pem
    # La implementación hace .strip() sobre el env — el body comparable ignora trailing ws.
    assert get_runtime_public_key_pem().strip() == override_body
