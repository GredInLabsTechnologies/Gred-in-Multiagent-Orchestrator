from tools.gimo_server.services.workspace.workspace_policy_service import WorkspacePolicyService


def test_chatgpt_apps_are_limited_to_ephemeral():
    assert WorkspacePolicyService.resolve_effective_mode(
        requested_mode="ephemeral",
        surface=WorkspacePolicyService.SURFACE_CHATGPT_APP,
    ) == "ephemeral"


def test_chatgpt_apps_reject_source_repo_mode():
    try:
        WorkspacePolicyService.resolve_effective_mode(
            requested_mode="source_repo",
            surface=WorkspacePolicyService.SURFACE_CHATGPT_APP,
        )
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("chatgpt_app surface must reject source_repo mode")


def test_sovereign_surfaces_allow_source_repo_mode():
    assert WorkspacePolicyService.resolve_effective_mode(
        requested_mode="source_repo",
        surface=WorkspacePolicyService.SURFACE_OPERATOR,
    ) == "source_repo"


def test_chatgpt_app_uses_chatgpt_orchestrator_authority():
    assert (
        WorkspacePolicyService.orchestrator_authority_for_surface(
            WorkspacePolicyService.SURFACE_CHATGPT_APP
        )
        == WorkspacePolicyService.ORCHESTRATOR_AUTHORITY_CHATGPT_APP
    )
    assert WorkspacePolicyService.can_surface_select_orchestrator(
        WorkspacePolicyService.SURFACE_CHATGPT_APP
    ) is False
    assert WorkspacePolicyService.can_surface_select_worker_model(
        WorkspacePolicyService.SURFACE_CHATGPT_APP
    ) is False


def test_operator_surface_uses_gimo_orchestrator_authority():
    assert (
        WorkspacePolicyService.orchestrator_authority_for_surface(
            WorkspacePolicyService.SURFACE_OPERATOR
        )
        == WorkspacePolicyService.ORCHESTRATOR_AUTHORITY_GIMO
    )
    assert WorkspacePolicyService.can_surface_select_orchestrator(
        WorkspacePolicyService.SURFACE_OPERATOR
    ) is True
    assert WorkspacePolicyService.can_surface_select_worker_model(
        WorkspacePolicyService.SURFACE_OPERATOR
    ) is True


def test_only_source_repo_workspace_allows_experimental_policy():
    assert WorkspacePolicyService.allows_experimental_policy("source_repo") is True
    assert WorkspacePolicyService.allows_experimental_policy("ephemeral") is False
