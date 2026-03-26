import pytest
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from tools.gimo_server.services.context_indexer import ContextIndexer
from tools.gimo_server.services.router_pm import RouterPM
from tools.gimo_server.services.sandbox_service import SandboxService
from tools.gimo_server.ops_models import RepoContext, StrictContract, IntentClass
from tools.gimo_server.services.slice0_orchestrator import Slice0Orchestrator

# --- ContextIndexer Tests ---

def test_context_indexer_empty_repo(tmp_path):
    """Test fallback when no recognized files exist."""
    context = ContextIndexer.build_context(str(tmp_path))
    assert isinstance(context, RepoContext)
    assert context.paths_of_interest == ["."]
    assert context.stack == []
    assert context.commands == []

def test_context_indexer_python_repo(tmp_path):
    """Test Python stack inference."""
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname='test'\nfastapi='1'", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    
    context = ContextIndexer.build_context(str(tmp_path))
    assert "Python" in context.stack
    assert "Fastapi" in context.stack
    assert "tests/" in context.paths_of_interest
    assert "pytest tests" in context.commands

def test_context_indexer_node_repo(tmp_path):
    """Test Node.js stack inference."""
    pkg_json = '{"dependencies": {"react": "^18.0.0"}, "scripts": {"test": "jest"}}'
    (tmp_path / "package.json").write_text(pkg_json, encoding="utf-8")
    (tmp_path / "src").mkdir()
    
    context = ContextIndexer.build_context(str(tmp_path))
    assert "Node.js" in context.stack
    assert "React" in context.stack
    assert "npm run test" in context.commands
    assert "src/" in context.paths_of_interest

# --- RouterPM Tests ---

@pytest.mark.asyncio
async def test_router_pm_parsing_clean_json():
    """Test RouterPM correctly parses a clean JSON response."""
    with patch("tools.gimo_server.services.provider_service.ProviderService.static_generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {
            "content": '{"objective":"Implement login","constraints":["No external libs"],"acceptance_criteria":["Returns 200 OM auth"],"execution":{"intent_class":"feature"},"out_of_scope":["Registration"]}'
        }
        
        ctx = RepoContext(stack=["Python"], commands=[], paths_of_interest=[], env_notes="")
        contract = await RouterPM.generate_contract("Build login", ctx)
        
        assert isinstance(contract, StrictContract)
        assert contract.objective == "Implement login"
        assert contract.execution.intent_class == IntentClass.feature
        assert contract.constraints == ["No external libs"]

@pytest.mark.asyncio
async def test_router_pm_parsing_markdown_json():
    """Test RouterPM correctly extracts JSON from a markdown code block."""
    with patch("tools.gimo_server.services.provider_service.ProviderService.static_generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {
            "content": '```json\n{"objective":"Fix the database connection bug","constraints":[],"acceptance_criteria":["DB connects successfully"],"execution":{"intent_class":"bugfix"},"out_of_scope":[]}\n```'
        }
        
        ctx = RepoContext(stack=[], commands=[], paths_of_interest=[], env_notes="")
        contract = await RouterPM.generate_contract("Fix the db connection", ctx)
        
        assert contract.execution.intent_class == IntentClass.bugfix

# --- SandboxService Tests ---

def test_sandbox_service_paths():
    """Verify SandboxService derives canonical sandbox paths from the ephemeral workspace root."""
    settings = SimpleNamespace(ephemeral_repos_dir=Path("/tmp/ephemeral-root"))
    with patch("tools.gimo_server.services.sandbox_service.get_settings", return_value=settings):
        assert SandboxService._workspace_path("run-123") == settings.ephemeral_repos_dir / SandboxService._workspace_id("run-123")

# --- Orchestrator Flow Tests (Basic import and sanity) ---

def test_orchestrator_imports():
    """Empirical check that Slice0Orchestrator can be imported and initialized."""
    assert callable(Slice0Orchestrator.run_pipeline)
