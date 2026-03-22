import os
import tempfile
from pathlib import Path

# Mock config object
class MockDict(dict):
    pass

class MockProviderEntry:
    pass

class MockProviderConfig:
    def __init__(self, active, orch_prov=None, work_prov=None):
        self.active = active
        self.orchestrator_provider = orch_prov
        self.worker_provider = work_prov
        self.orchestrator_model = "gpt-4o"
        self.worker_model = "llama3"
        self.providers = {"openai-cloud": MockProviderEntry(), "ollama-local": MockProviderEntry()}

from tools.gimo_server.services.model_router_service import ModelRouterService
from tools.gimo_server.services.context_indexer import ContextIndexer

def test_routing():
    print("--- Testing Two-Tier Routing ---")
    cfg = MockProviderConfig("default-prov", "openai-cloud", "ollama-local")
    
    # Test orchestrator task
    p, m = ModelRouterService.resolve_tier_routing("review", cfg)
    print(f"Review Task -> Provider: {p}, Model: {m}")
    assert p == "openai-cloud"
    assert m == "gpt-4o"
    
    p, m = ModelRouterService.resolve_tier_routing("disruptive_planning", cfg)
    print(f"Disruptive Planning Task -> Provider: {p}, Model: {m}")
    assert p == "openai-cloud"
    
    # Test worker task
    p, m = ModelRouterService.resolve_tier_routing("coding", cfg)
    print(f"Coding Task -> Provider: {p}, Model: {m}")
    assert p == "ollama-local"
    assert m == "llama3"
    
    # Test unknown task (should be None, effectively using default)
    p, m = ModelRouterService.resolve_tier_routing("unknown", cfg)
    print(f"Unknown Task -> Provider: {p}, Model: {m}")
    assert p is None
    print("Routing logic passes.\n")

def test_context_indexer():
    print("--- Testing ContextIndexer Path Traversal Prevention ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        safe_file = root / "safe.txt"
        safe_file.write_text("Safe content")
        
        parent_file = root.parent / "danger.txt"
        try:
            parent_file.write_text("Danger content")
        except PermissionError:
            pass # Can't write to parent temp, that's fine

        # 1. Normal scope
        res1 = ContextIndexer.extract_file_contents(str(root), ["safe.txt"])
        print("Test Safe File:\n", res1.strip())
        assert "Safe content" in res1
        
        # 2. Path Traversal attack
        res2 = ContextIndexer.extract_file_contents(str(root), ["../danger.txt"])
        print("\nTest Traversal Attack:\n", res2.strip())
        assert "Access denied: Path outside workspace" in res2
        
        # 3. Absolute path attack
        if os.name == 'nt':
            bad_path = "C:/Windows/System32/drivers/etc/hosts"
        else:
            bad_path = "/etc/passwd"
        res3 = ContextIndexer.extract_file_contents(str(root), [bad_path])
        print(f"\nTest Absolute Path Attack ({bad_path}):\n", res3.strip())
        assert "Access denied: Path outside workspace" in res3

    print("ContextIndexer path protection passes.\n")

if __name__ == "__main__":
    test_routing()
    test_context_indexer()
    print("✅ All Phase C critical fix tests passed.")
