from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.gimo_server.schemas.draft_validation import DraftCreateRequest
from tools.gimo_server.services.app_draft_service import AppDraftService, AppDraftSessionNotFoundError


def test_create_validated_draft_persists_canonical_ops_draft():
    validated = {
        "validated_task_spec": {
            "base_commit": "abc123",
            "repo_handle": "repo_h",
            "allowed_paths": ["app.py"],
            "acceptance_criteria": "Make it work",
            "evidence_hash": "hash1",
            "context_pack_id": "ctx1",
            "worker_model": "gpt-4o",
            "requires_manual_merge": True,
        },
        "repo_context_pack": {
            "id": "ctx1",
            "session_id": "s1",
            "repo_handle": "repo_h",
            "base_commit": "abc123",
            "read_proofs": [],
            "allowed_paths": ["app.py"],
        },
    }
    created_draft = SimpleNamespace(id="d_123")

    with patch(
        "tools.gimo_server.services.app_draft_service.AppSessionService.get_session",
        return_value={"id": "s1"},
    ), patch(
        "tools.gimo_server.services.app_draft_service.DraftValidationService.validate_draft",
        return_value=validated,
    ) as mock_validate, patch(
        "tools.gimo_server.services.app_draft_service.OpsService.create_draft",
        return_value=created_draft,
    ) as mock_create:
        result = AppDraftService.create_validated_draft(
            "s1",
            DraftCreateRequest(acceptance_criteria="Make it work", allowed_paths=["app.py"]),
        )

    assert result.draft_id == "d_123"
    assert result.validated_task_spec.repo_handle == "repo_h"
    mock_validate.assert_called_once()
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["operator_class"] == "cognitive_agent"
    assert mock_create.call_args.kwargs["context"]["operator_class"] == "cognitive_agent"
    assert mock_create.call_args.kwargs["context"]["surface"] == "chatgpt_app"


def test_create_validated_draft_fails_honestly_without_session():
    with patch(
        "tools.gimo_server.services.app_draft_service.AppSessionService.get_session",
        return_value=None,
    ), patch(
        "tools.gimo_server.services.app_draft_service.DraftValidationService.validate_draft",
    ) as mock_validate, patch(
        "tools.gimo_server.services.app_draft_service.OpsService.create_draft",
    ) as mock_create:
        with pytest.raises(AppDraftSessionNotFoundError, match="Session not found"):
            AppDraftService.create_validated_draft(
                "missing",
                {"acceptance_criteria": "Make it work", "allowed_paths": ["app.py"]},
            )

    mock_validate.assert_not_called()
    mock_create.assert_not_called()
