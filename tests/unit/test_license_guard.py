import json
import time
import base64
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from tools.gimo_server.security.license_guard import LicenseGuard, LicenseStatus

class TestLicenseGuard:
    @pytest.fixture
    def mock_settings(self, tmp_path):
        settings = MagicMock()
        settings.license_key = "GIMO-TEST-KEY-123456"
        settings.license_validate_url = "https://test.gimo.web/validate"
        settings.license_cache_path = str(tmp_path / ".gimo_license_test")
        settings.license_grace_days = 3
        settings.license_recheck_hours = 24
        settings.license_allow_debug_bypass = False
        settings.license_public_key_pem = None # Use embedded
        return settings

    def test_grace_period_enforcement_valid(self, mock_settings):
        """Verify that license is valid within the 3-day grace period."""
        guard = LicenseGuard(mock_settings)
        
        # Mock a cache that is 2 days old
        now = time.time()
        two_days_ago = now - (2 * 86400)
        
        mock_cache = {
            "token": "valid.jwt.token",
            "last_online_ts": two_days_ago,
            "fingerprint_components": {},
            "file_hash": guard._compute_own_hash(),
            "guard_version": "1.0.0"
        }
        
        with patch.object(LicenseGuard, "_load_cache", return_value=mock_cache), \
             patch("tools.gimo_server.security.license_guard._verify_jwt_ed25519", return_value={"plan": "standard", "iat": now - 3600}):
            
            status = guard._validate_offline()
            assert status.valid is True
            assert "offline_cache" in status.reason

    def test_grace_period_enforcement_expired(self, mock_settings):
        """Verify that license is rejected after the 3-day grace period."""
        guard = LicenseGuard(mock_settings)
        
        # Mock a cache that is 4 days old
        now = time.time()
        four_days_ago = now - (4 * 86400)
        
        mock_cache = {
            "token": "valid.jwt.token",
            "last_online_ts": four_days_ago,
            "fingerprint_components": {},
            "file_hash": guard._compute_own_hash(),
            "guard_version": "1.0.0"
        }
        
        with patch.object(LicenseGuard, "_load_cache", return_value=mock_cache), \
             patch("tools.gimo_server.security.license_guard._verify_jwt_ed25519", return_value={"plan": "standard", "iat": now - 3600}):
            
            status = guard._validate_offline()
            assert status.valid is False
            assert "Grace period expired" in status.reason

    def test_anti_tamper_detection(self, mock_settings):
        """Verify that modifying the license_guard.py file triggers a tamper alert."""
        guard = LicenseGuard(mock_settings)
        
        mock_cache = {
            "token": "token",
            "last_online_ts": time.time(),
            "file_hash": "original_hash",
            "guard_version": "1.0.0"
        }
        
        # Simulate different current hash
        with patch.object(LicenseGuard, "_load_cache", return_value=mock_cache), \
             patch.object(LicenseGuard, "_compute_own_hash", return_value="malicious_hash"):
            
            assert guard._verify_file_integrity() is False

    def test_anti_tamper_update_allowed(self, mock_settings):
        """Verify that a version bump allows the hash to change (legitimate update)."""
        guard = LicenseGuard(mock_settings)
        
        mock_cache = {
            "token": "token",
            "last_online_ts": time.time(),
            "file_hash": "old_hash",
            "guard_version": "0.9.0" # Old version
        }
        
        with patch.object(LicenseGuard, "_load_cache", return_value=mock_cache), \
             patch.object(LicenseGuard, "_compute_own_hash", return_value="new_hash"):
            
            assert guard._verify_file_integrity() is True
            assert guard._guard_version_updated is True

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_online_validation_saves_cache(self, mock_post, mock_settings):
        """Verify that successful online validation saves a fresh cache."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "valid": True,
                "token": "new.jwt.token",
                "plan": "pro"
            }
        )
        
        guard = LicenseGuard(mock_settings)
        
        with patch.object(LicenseGuard, "_save_cache") as mock_save:
            status = await guard._validate_online()
            assert status.valid is True
            assert status.plan == "pro"
            mock_save.assert_called_once()
