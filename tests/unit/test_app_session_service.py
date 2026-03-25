import pytest
import os
import json
from pathlib import Path
from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.config import get_settings

def test_create_get_session():
    """Verifica la creación y recuperación de una sesión de App."""
    session = AppSessionService.create_session({"test": "data"})
    assert session["id"] is not None
    assert session["metadata"]["test"] == "data"
    
    retrieved = AppSessionService.get_session(session["id"])
    assert retrieved is not None
    assert retrieved["id"] == session["id"]
    assert retrieved["metadata"]["test"] == "data"

def test_bind_repo_opaque_handle(tmp_path):
    """Verifica la vinculación de un repositorio mediante handle opaco."""
    settings = get_settings()
    registry_path = settings.repo_registry_path
    
    # Respaldamos el registry si existe
    old_content = None
    if registry_path.exists():
        old_content = registry_path.read_text()

    try:
        test_repo_path = str(tmp_path / "my-repo")
        os.makedirs(test_repo_path, exist_ok=True)
        
        registry_data = {"repos": [test_repo_path]}
        registry_path.write_text(json.dumps(registry_data))
        
        # Obtenemos el mapping para encontrar el handle generado
        mapping = AppSessionService.get_handle_mapping()
        assert len(mapping) > 0
        handle = list(mapping.keys())[0]
        
        # El handle no debe contener la ruta host
        assert test_repo_path not in handle
        
        session = AppSessionService.create_session()
        success = AppSessionService.bind_repo(session["id"], handle)
        assert success is True
        
        updated = AppSessionService.get_session(session["id"])
        assert updated["repo_id"] == handle
        
        # Fallback de seguridad: el handle es consistente
        assert AppSessionService.get_path_from_handle(handle) == test_repo_path
    finally:
        # Restauramos el registry
        if old_content:
            registry_path.write_text(old_content)

def test_purge_session():
    """Verifica que la sesión se elimine correctamente."""
    session = AppSessionService.create_session()
    session_id = session["id"]
    assert AppSessionService.get_session(session_id) is not None
    
    assert AppSessionService.purge_session(session_id) is True
    assert AppSessionService.get_session(session_id) is None
