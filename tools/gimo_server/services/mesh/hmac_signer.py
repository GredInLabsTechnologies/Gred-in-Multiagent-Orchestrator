"""HMAC-SHA256 signer for mDNS TXT records and QR payloads.

Shared by MdnsAdvertiser (signs TXT record) and mesh_router (signs QR payload).
The signature is truncated to 32 hex chars (128 bits) per NIST recommendation
for HMAC truncation. Compact enough for QR payloads and TXT records.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac


def sign_payload(token: str, payload: str) -> str:
    """HMAC-SHA256 of payload keyed by token, truncated to 32 hex chars (128 bits)."""
    mac = _hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


def verify_payload(token: str, payload: str, sig: str) -> bool:
    """Constant-time comparison of expected vs provided signature."""
    expected = sign_payload(token, payload)
    return _hmac.compare_digest(expected, sig)
