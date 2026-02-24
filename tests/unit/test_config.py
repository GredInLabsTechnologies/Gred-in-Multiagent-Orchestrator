import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from tools.gimo_server.ops_models import (
    UserEconomyConfig,
    CascadeConfig,
    EcoModeConfig,
    ProviderBudget
)
from tools.gimo_server.config import _load_or_create_token


def test_token_creation(tmp_path):
    token_file = tmp_path / ".token"
    with patch("tools.gimo_server.config.ORCH_TOKEN_FILE", token_file):
        with patch.dict(os.environ, {"ORCH_TOKEN": ""}):
            if token_file.exists():
                token_file.unlink()
            token = _load_or_create_token()
            assert len(token) > 20
            assert token_file.exists()
            assert token_file.read_text() == token


def test_token_from_env():
    with patch.dict(os.environ, {"ORCH_TOKEN": "env-token"}):
        token = _load_or_create_token()
        assert token == "env-token"


def test_token_from_file(tmp_path):
    token_file = tmp_path / ".token"
    token_file.write_text("file-token")
    with patch("tools.gimo_server.config.ORCH_TOKEN_FILE", token_file):
        with patch.dict(os.environ, {"ORCH_TOKEN": ""}):
            token = _load_or_create_token()
            assert token == "file-token"


def test_token_file_read_error(tmp_path):
    token_file = tmp_path / ".token"
    with patch("tools.gimo_server.config.ORCH_TOKEN_FILE", token_file):
        with patch.dict(os.environ, {"ORCH_TOKEN": ""}):
            with patch.object(Path, "read_text", side_effect=Exception("read error")):
                token = _load_or_create_token()
                assert len(token) > 0

# ── User Economy Config ───────────────────────────────────

class TestUserEconomyConfig:
    def test_default_values(self):
        config = UserEconomyConfig()
        assert config.autonomy_level == "manual"
        assert config.alert_thresholds == [50, 25, 10]

    def test_global_budget_validation(self):
        config = UserEconomyConfig(global_budget_usd=100.0)
        assert config.global_budget_usd == 100.0
        with pytest.raises(ValidationError):
            UserEconomyConfig(global_budget_usd=-1.0)

    def test_alert_thresholds_validation(self):
        config = UserEconomyConfig(alert_thresholds=[10, 90])
        assert config.alert_thresholds == [90, 10]
        with pytest.raises(ValidationError):
            UserEconomyConfig(alert_thresholds=[101])

class TestCascadeConfig:
    def test_quality_threshold_validation(self):
        config = CascadeConfig(quality_threshold=50)
        assert config.quality_threshold == 50
        with pytest.raises(ValidationError):
            CascadeConfig(quality_threshold=101)

class TestEcoModeConfig:
    def test_confidence_threshold_validation(self):
        config = EcoModeConfig(confidence_threshold_aggressive=0.5)
        assert config.confidence_threshold_aggressive == 0.5
        with pytest.raises(ValidationError):
            EcoModeConfig(confidence_threshold_aggressive=1.1)
