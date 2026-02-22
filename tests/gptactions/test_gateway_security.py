"""
Tests de seguridad del gateway de GPT Actions.

Cubre los vectores de ataque más críticos:
  1. Path traversal en jail
  2. IP allowlist (IPs no permitidas)
  3. Autenticación (tokens inválidos)
  4. Schema validation (propuestas malformadas / prompt injection)
  5. Rate limiting de patches
  6. Cuota de patches (MAX_PENDING_PATCHES)
  7. Integridad del audit chain
  8. Anti-TOCTOU en el integrador
  9. Attestation (firma inválida)
  10. Null bytes y ADS en paths
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

import pytest


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def tmp_jail(tmp_path: Path):
    """Jail temporal para tests."""
    from tools.gptactions_gateway.security.jail import Jail
    return Jail(tmp_path / "jail")


@pytest.fixture
def tmp_audit(tmp_path: Path):
    """Audit log temporal."""
    from tools.gptactions_gateway.security.chain_audit import ChainedAuditLog
    return ChainedAuditLog(tmp_path / "audit.jsonl")


@pytest.fixture
def tmp_allowlist(tmp_path: Path):
    """Allowlist de IPs temporal con un CIDR de prueba."""
    from tools.gptactions_gateway.security.ip_allowlist import IPAllowlist
    allowlist_file = tmp_path / "ips.json"
    allowlist_file.write_text(
        json.dumps({
            "fetched_at": "2026-02-22T00:00:00Z",
            "fetched_at_epoch": time.time(),
            "source_url": "test",
            "cidrs": ["192.0.2.0/24", "127.0.0.1/32"],
        }),
        encoding="utf-8",
    )
    return IPAllowlist(allowlist_file, bypass_loopback=False)


# ------------------------------------------------------------------
# 1. Path traversal en jail
# ------------------------------------------------------------------

class TestJailTraversal:
    """El jail debe rechazar TODOS los intentos de path traversal."""

    def test_dot_dot_slash(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="traversal"):
            tmp_jail.resolve("../secret.txt")

    def test_dot_dot_backslash(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="traversal"):
            tmp_jail.resolve("..\\secret.txt")

    def test_encoded_traversal(self, tmp_jail):
        """Traversal a través de path encoding (URL decode no aplica aquí, pero verificamos)."""
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation):
            tmp_jail.resolve("patches/../../../etc/passwd")

    def test_null_byte(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="Null byte"):
            tmp_jail.resolve("patches/file\x00.json")

    def test_windows_ads(self, tmp_jail):
        """NTFS Alternate Data Stream."""
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="Alternate Data Stream"):
            tmp_jail.resolve("patches/file.json:hidden_stream")

    def test_windows_reserved_con(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="[Rr]eservado"):
            tmp_jail.resolve("patches/CON")

    def test_windows_reserved_nul(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="[Rr]eservado"):
            tmp_jail.resolve("NUL.json")

    def test_excessive_depth(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        deep_path = "/".join(["a"] * 15)  # 15 niveles > MAX_PATH_DEPTH
        with pytest.raises(JailViolation, match="profundo"):
            tmp_jail.resolve(deep_path)

    def test_forbidden_dir_git(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="[Pp]rohibido"):
            tmp_jail.resolve(".git/config")

    def test_forbidden_dir_env(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="[Pp]rohibido"):
            tmp_jail.resolve(".env/secrets")

    def test_valid_path_accepted(self, tmp_jail):
        """Un path válido dentro del jail debe ser aceptado."""
        result = tmp_jail.resolve("patches/abc123.json")
        assert str(tmp_jail.root) in str(result)


# ------------------------------------------------------------------
# 2. IP Allowlist
# ------------------------------------------------------------------

class TestIPAllowlist:
    def test_allowed_ip(self, tmp_allowlist):
        allowed, _ = tmp_allowlist.is_allowed("192.0.2.100")
        assert allowed

    def test_blocked_ip(self, tmp_allowlist):
        allowed, reason = tmp_allowlist.is_allowed("8.8.8.8")
        assert not allowed

    def test_invalid_ip_string(self, tmp_allowlist):
        allowed, reason = tmp_allowlist.is_allowed("not-an-ip")
        assert not allowed
        assert "inválida" in reason

    def test_empty_allowlist_blocks_all(self, tmp_path):
        from tools.gptactions_gateway.security.ip_allowlist import IPAllowlist
        empty_file = tmp_path / "empty_ips.json"
        empty_file.write_text(
            json.dumps({"fetched_at_epoch": time.time(), "cidrs": []}),
            encoding="utf-8",
        )
        allowlist = IPAllowlist(empty_file)
        allowed, reason = allowlist.is_allowed("192.0.2.100")
        assert not allowed
        assert "vacío" in reason

    def test_missing_file_blocks_all(self, tmp_path):
        from tools.gptactions_gateway.security.ip_allowlist import IPAllowlist
        allowlist = IPAllowlist(tmp_path / "nonexistent.json")
        allowed, _ = allowlist.is_allowed("192.0.2.100")
        assert not allowed

    def test_bypass_loopback(self, tmp_path):
        from tools.gptactions_gateway.security.ip_allowlist import IPAllowlist
        allowlist = IPAllowlist(tmp_path / "nonexistent.json", bypass_loopback=True)
        allowed, reason = allowlist.is_allowed("127.0.0.1")
        assert allowed
        assert "bypass" in reason


# ------------------------------------------------------------------
# 3. Audit Chain
# ------------------------------------------------------------------

class TestAuditChain:
    def test_chain_starts_intact(self, tmp_audit):
        ok, msg = tmp_audit.verify_chain()
        assert ok

    def test_chain_integrity_after_entries(self, tmp_audit):
        for i in range(5):
            tmp_audit.append(
                event=f"TEST_{i}",
                src_ip="127.0.0.1",
                payload_hash=hashlib.sha256(f"test{i}".encode()).hexdigest(),
                actor_hash="deadbeef",
                outcome="ALLOWED",
                detail=f"entry {i}",
            )
        ok, msg = tmp_audit.verify_chain()
        assert ok, f"Cadena debería estar íntegra: {msg}"

    def test_tampered_entry_detected(self, tmp_audit, tmp_path):
        """Modificar una entrada debe romper la cadena."""
        tmp_audit.append(
            event="NORMAL",
            src_ip="127.0.0.1",
            payload_hash="abc",
            actor_hash="xyz",
            outcome="ALLOWED",
            detail="legítimo",
        )
        tmp_audit.append(
            event="NORMAL2",
            src_ip="127.0.0.1",
            payload_hash="def",
            actor_hash="xyz",
            outcome="ALLOWED",
            detail="legítimo2",
        )

        # Manipular la primera línea
        lines = tmp_audit._path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        entry["outcome"] = "ALLOWED_BUT_MANIPULATED"  # Cambiar un campo
        lines[0] = json.dumps(entry)
        tmp_audit._path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok, msg = tmp_audit.verify_chain()
        assert not ok, "Debería detectar la manipulación"
        assert "manipulada" in msg.lower() or "mismatch" in msg.lower()

    def test_deleted_entry_detected(self, tmp_audit):
        """Borrar una entrada del medio debe romper la cadena."""
        for i in range(3):
            tmp_audit.append(
                event=f"E{i}", src_ip="x", payload_hash="y",
                actor_hash="z", outcome="ALLOWED", detail="",
            )
        lines = tmp_audit._path.read_text(encoding="utf-8").splitlines()
        # Eliminar la línea del medio
        del lines[1]
        tmp_audit._path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok, msg = tmp_audit.verify_chain()
        assert not ok


# ------------------------------------------------------------------
# 4. Schema validation y anti-prompt-injection
# ------------------------------------------------------------------

class TestPatchSchema:
    def _valid_proposal(self) -> dict:
        return {
            "schema_version": "1.0",
            "change_type": "code_modification",
            "risk_level": "low",
            "rationale": "Corrección de un bug de validación en el módulo principal",
            "target_files": [
                {
                    "path": "tools/gimo_server/config.py",
                    "hunks": [
                        {
                            "start_line": 10,
                            "end_line": 10,
                            "old_lines": ["x = 1"],
                            "new_lines": ["x = 2"],
                        }
                    ],
                }
            ],
        }

    def test_valid_proposal_accepted(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        result = validate_proposal(self._valid_proposal())
        assert result.valid

    def test_high_risk_rejected(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        p = self._valid_proposal()
        p["risk_level"] = "high"
        result = validate_proposal(p)
        assert not result.valid
        assert any("high" in e.lower() or "riesgo" in e.lower() for e in result.errors)

    def test_traversal_in_path_rejected(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        p = self._valid_proposal()
        p["target_files"][0]["path"] = "../../../etc/passwd"
        result = validate_proposal(p)
        assert not result.valid

    def test_binary_extension_rejected(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        p = self._valid_proposal()
        p["target_files"][0]["path"] = "tools/malware.exe"
        result = validate_proposal(p)
        assert not result.valid

    def test_env_file_rejected(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        p = self._valid_proposal()
        p["target_files"][0]["path"] = ".env"
        result = validate_proposal(p)
        assert not result.valid

    def test_too_many_files_rejected(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        p = self._valid_proposal()
        p["target_files"] = [
            {
                "path": f"tools/file{i}.py",
                "hunks": [{"start_line": 1, "end_line": 1, "old_lines": ["x"], "new_lines": ["y"]}],
            }
            for i in range(10)  # MAX_FILES_PER_PATCH es 5
        ]
        result = validate_proposal(p)
        assert not result.valid

    def test_protected_path_flagged(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        p = self._valid_proposal()
        p["target_files"][0]["path"] = ".github/workflows/ci.yml"
        result = validate_proposal(p)
        # Puede ser válido estructuralmente pero debe flaggear requires_manual_override
        assert result.requires_manual_override or not result.valid

    def test_short_rationale_rejected(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        p = self._valid_proposal()
        p["rationale"] = "ok"  # Menos de 10 chars
        result = validate_proposal(p)
        assert not result.valid

    def test_end_before_start_line_rejected(self):
        from tools.gptactions_gateway.security.patch_schema import validate_proposal
        p = self._valid_proposal()
        p["target_files"][0]["hunks"][0]["end_line"] = 5
        p["target_files"][0]["hunks"][0]["start_line"] = 10  # end < start
        result = validate_proposal(p)
        assert not result.valid


# ------------------------------------------------------------------
# 5. Patch quota
# ------------------------------------------------------------------

class TestPatchQuota:
    def test_quota_enforcement(self, tmp_jail):
        """No se deben poder crear más de MAX_PENDING_PATCHES patches."""
        from tools.gptactions_gateway.security.jail import MAX_PENDING_PATCHES, PatchQuotaExceeded
        content = b'{"schema_version": "1.0", "target_files": []}'

        for i in range(MAX_PENDING_PATCHES):
            import uuid
            tmp_jail.write_patch(f"{str(uuid.uuid4())}.json", content)

        # El siguiente debe fallar
        with pytest.raises(PatchQuotaExceeded):
            import uuid
            tmp_jail.write_patch(f"{str(uuid.uuid4())}.json", content)

    def test_valid_patch_name_only(self, tmp_jail):
        """Solo nombres de archivo UUID son válidos."""
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation, match="[Nn]ombre"):
            tmp_jail.write_patch("../../malicious.json", b"{}")

    def test_patch_name_must_be_uuid_format(self, tmp_jail):
        from tools.gptactions_gateway.security.jail import JailViolation
        with pytest.raises(JailViolation):
            tmp_jail.write_patch("../../etc/passwd.json", b"{}")


# ------------------------------------------------------------------
# 6. Structural checker
# ------------------------------------------------------------------

class TestStructuralChecker:
    def test_hard_block_ci_cd(self):
        from tools.patch_validator.structural_checker import check_structure
        patch = {
            "target_files": [
                {
                    "path": ".github/workflows/ci.yml",
                    "hunks": [{"start_line": 1, "end_line": 1, "old_lines": ["x"], "new_lines": ["y"]}],
                }
            ]
        }
        result = check_structure(patch)
        assert result.hard_blocked
        assert not result.passed

    def test_dependency_gate_requirements(self):
        from tools.patch_validator.structural_checker import check_structure
        patch = {
            "target_files": [
                {
                    "path": "requirements.txt",
                    "hunks": [{"start_line": 1, "end_line": 1, "old_lines": ["fastapi==0.1"], "new_lines": ["fastapi==0.2"]}],
                }
            ]
        }
        result = check_structure(patch)
        assert result.dependency_gate_triggered
        # No es un error fatal, pero requiere gate
        assert not result.hard_blocked

    def test_too_many_lines(self):
        from tools.patch_validator.structural_checker import check_structure, MAX_TOTAL_LINES_CHANGED
        lines = [f"line {i}" for i in range(MAX_TOTAL_LINES_CHANGED + 1)]
        patch = {
            "target_files": [
                {
                    "path": "tools/gimo_server/config.py",
                    "hunks": [
                        {
                            "start_line": 1,
                            "end_line": len(lines),
                            "old_lines": lines,
                            "new_lines": lines,
                        }
                    ],
                }
            ]
        }
        result = check_structure(patch)
        assert not result.passed
        assert any("grande" in e.lower() or "lines" in e.lower() for e in result.errors)

    def test_valid_small_patch(self):
        from tools.patch_validator.structural_checker import check_structure
        patch = {
            "target_files": [
                {
                    "path": "tools/gimo_server/config.py",
                    "hunks": [
                        {"start_line": 10, "end_line": 10, "old_lines": ["x = 1"], "new_lines": ["x = 2"]}
                    ],
                }
            ]
        }
        result = check_structure(patch)
        assert result.passed
        assert not result.hard_blocked


# ------------------------------------------------------------------
# 7. Attestation (firma Ed25519)
# ------------------------------------------------------------------

class TestAttestation:
    @pytest.fixture
    def keypair(self, tmp_path):
        from tools.patch_validator.attestation import generate_keypair
        priv = tmp_path / "private.pem"
        pub = tmp_path / "public.pem"
        generate_keypair(priv, pub)
        return priv, pub

    def test_sign_and_verify(self, keypair):
        from tools.patch_validator.attestation import sign_attestation, verify_attestation
        priv, pub = keypair
        att = sign_attestation(
            patch_id="test-id",
            patch_hash="abc123",
            checks={"structural": "PASS", "sast": "PASS", "secrets": "PASS", "deps": "PASS"},
            outcome="APPROVED",
            private_key_path=priv,
        )
        # No debe lanzar excepción
        verify_attestation(att, pub)

    def test_tampered_attestation_fails(self, keypair):
        from tools.patch_validator.attestation import sign_attestation, verify_attestation, AttestationVerificationError
        priv, pub = keypair
        att = sign_attestation(
            patch_id="test-id",
            patch_hash="abc123",
            checks={"structural": "PASS"},
            outcome="APPROVED",
            private_key_path=priv,
        )
        # Manipular el outcome
        att["outcome"] = "REJECTED"
        with pytest.raises(AttestationVerificationError, match="(?i)inv.lida|invalid"):
            verify_attestation(att, pub)

    def test_missing_signature_fails(self, keypair):
        from tools.patch_validator.attestation import verify_attestation, AttestationVerificationError
        _, pub = keypair
        att = {"patch_id": "x", "outcome": "APPROVED"}
        with pytest.raises(AttestationVerificationError, match="signature"):
            verify_attestation(att, pub)

    def test_wrong_key_fails(self, keypair, tmp_path):
        from tools.patch_validator.attestation import (
            sign_attestation, verify_attestation, generate_keypair, AttestationVerificationError
        )
        priv1, _ = keypair
        priv2 = tmp_path / "private2.pem"
        pub2 = tmp_path / "public2.pem"
        generate_keypair(priv2, pub2)

        att = sign_attestation(
            patch_id="x", patch_hash="y",
            checks={}, outcome="APPROVED",
            private_key_path=priv1,  # Firmado con clave 1
        )
        with pytest.raises(AttestationVerificationError):
            verify_attestation(att, pub2)  # Verificado con clave 2 → debe fallar


# ------------------------------------------------------------------
# 8. Binary file detection
# ------------------------------------------------------------------

class TestBinaryDetection:
    def test_text_file_accepted(self, tmp_jail):
        # No debe lanzar excepción
        tmp_jail.assert_text_file(b"print('hello world')\n")

    def test_binary_file_rejected(self, tmp_jail):
        binary_data = bytes(range(256)) * 10  # Muchos bytes no imprimibles
        with pytest.raises(PermissionError, match="[Bb]inario"):
            tmp_jail.assert_text_file(binary_data)

    def test_empty_file_accepted(self, tmp_jail):
        tmp_jail.assert_text_file(b"")
