import logging
from typing import Any, Dict
from pathlib import Path
from tools.gimo_server.version import __version__
from tools.gimo_server.config import REPO_ROOT_DIR
from tools.gimo_server.services.git_service import GitService
from tools.gimo_server.services.provider_service_impl import ProviderService
from tools.gimo_server.services.notice_policy_service import NoticePolicyService
from tools.gimo_server.services.conversation_service import ConversationService

logger = logging.getLogger("orchestrator.services.operator_status")

class OperatorStatusService:
    @classmethod
    def get_status_snapshot(cls) -> Dict[str, Any]:
        base_dir = Path(REPO_ROOT_DIR)
        
        branch = None
        dirty_files = []
        try:
            branch = GitService.get_current_branch(base_dir)
            dirty_files = GitService.get_changed_files(base_dir)
        except Exception:
            pass

        active_provider = None
        active_model = None
        permission_mode = None
        try:
            cfg = ProviderService.get_config()
            if cfg and cfg.roles and cfg.roles.orchestrator:
                active_provider = cfg.roles.orchestrator.provider_id
                active_model = cfg.roles.orchestrator.model
                if hasattr(cfg.roles.orchestrator, "permission_mode"):
                    permission_mode = cfg.roles.orchestrator.permission_mode
        except Exception:
            pass

        last_thread_id = None
        last_turn_id = None
        try:
            threads = ConversationService.list_threads()
            if threads:
                last_thread_id = threads[0].id
                if threads[0].turns:
                    last_turn_id = threads[0].turns[-1].id
        except Exception:
            pass

        snapshot = {
            "repo": str(base_dir.name) if base_dir.exists() else None,
            "branch": branch,
            "dirty_files": dirty_files,
            "active_provider": active_provider,
            "active_model": active_model,
            "permission_mode": permission_mode,
            "backend_status": {"authoritative": False, "reason": "Dynamic health checks not assigned to Phase 2 contracts"},
            "backend_version": __version__,
            "active_run": {"authoritative": False, "reason": "Run monitoring not assigned to Phase 2 contracts"},
            "active_stage": {"authoritative": False, "reason": "Stage tracking not assigned to Phase 2 contracts"},
            "budget_spend": {"authoritative": False, "reason": "Budget tracking not assigned to Phase 2 contracts"},
            "budget_limit": {"authoritative": False, "reason": "Budget tracking not assigned to Phase 2 contracts"},
            "context_percentage": {"authoritative": False, "reason": "Context monitoring not assigned to Phase 2 contracts"},
            "last_thread": last_thread_id,
            "last_turn": last_turn_id,
        }

        snapshot["alerts"] = NoticePolicyService.evaluate_all(snapshot)
        return snapshot
