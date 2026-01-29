# Dependency Map & Refactoring Guide (Surgical Mode)

## Module: main.py (God File)

### Functions to Move to `services/repo_service.py`
- `_list_repos()`
  - Deps: `GitService`, `config.REPO_ROOT_DIR`
- `_ensure_repo_registry(repos)`
  - Deps: `security.load_repo_registry`, `security.save_repo_registry`
- `_vitaminize_repo(target_repo)`
  - Deps: `config.VITAMINIZE_PACKAGE`, `config.BASE_DIR`
- `_walk_tree(target, max_depth)`
  - Deps: `config.SEARCH_EXCLUDE_DIRS`, `config.ALLOWED_EXTENSIONS`
- `_perform_search(base_dir, q, ext)`
  - Deps: `_should_skip_dir`, `_search_in_file`
- `_search_in_file(file_path, base_dir, q)`
  - Deps: `security.redact_sensitive_data`
- `_should_skip_dir(d)`
  - Deps: `config.SEARCH_EXCLUDE_DIRS`

### Functions to Move to `services/file_service.py`
- `_tail_audit_lines(limit)`
  - Deps: `config.AUDIT_LOG_PATH`
- Logic inside `get_file` (reading, snapshotting, line slicing) should be a service method.
  - Deps: `SnapshotService`, `config.MAX_LINES`, `config.MAX_BYTES`, `security.redact_sensitive_data`, `security.audit_log`

### Models to Move to `models.py`
- `RepoEntry` (Dataclass)
- `VitaminizeResponse` (BaseModel)
- `StatusResponse` (BaseModel)
- `UiStatusResponse` (BaseModel)
- `FileWriteRequest` (BaseModel)

### Routes to Move to `routes.py`
- All `@app.get` and `@app.post` handlers.
- **Dependency Flow:** Routes -> Services -> Security/Git/FileSystem.

### Core remaining in `main.py`
- `lifespan` (Context manager)
- `app` (FastAPI instance)
- `snapshot_cleanup_loop` (Background task) - *Optional: Could move to SnapshotService*
- Middleware (`allow_options_preflight`)
- Static files mounting

## External Connections (Imports to main.py)
1. `config.py`: BASE_DIR, REPO_ROOT_DIR, etc.
2. `security/__init__.py`: verify_token, validate_path, audit_log, etc.
3. `services/git_service.py`: GitService
4. `services/snapshot_service.py`: SnapshotService
5. `services/system_service.py`: SystemService

## Side-Effects Checklist
- `BASE_DIR.exists()` check (Line 105) -> Move to lifespan.
- `start_time = time.time()` (Line 108) -> Move to app state in lifespan.
- `_ensure_repo_registry` call is inside `list_repos` route (Line 235).
