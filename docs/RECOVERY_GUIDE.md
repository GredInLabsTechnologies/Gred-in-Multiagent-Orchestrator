# Handover & Recovery Guide: Gred-Repo-Orchestrator

## Current State & Integrity Findings
The orchestrator has been successfully extracted from a larger repository. The following hardening steps have been applied:
- **Relative Discovery**: `config.py` uses relative paths.
- **Startup Protection**: Scripts detect working directory automatically.
- **Registry Clean**: Stale paths removed.

## Data Recovery & Endpoints
The orchestrator acts as a secure gateway. To access data from a client:

### Core Endpoints
- **Registry**: `GET /ui/repos` - Lists managed repositories.
- **Active Repo**: `GET /ui/repos/active` - Returns the currently focused repository.
- **Audit Logs**: `GET /ui/audit` - Retrieves history.
- **Security State**: `GET /ui/security/events` - Lockdown status.

### Source Data Files
Critical data for migration/recovery:
- `tools/repo_orchestrator/repo_registry.json`
- `tools/repo_orchestrator/security_db.json`
- `tools/repo_orchestrator/allowed_paths.json`
- `logs/orchestrator_audit.log`

## Handover Instructions
1. **Hardening Global Paths**: Use `ORCH_REPO_ROOT` env var to override base path.
2. **Startup Scripts**: Run `scripts/start_orch.cmd` from any location.
3. **"Vitaminizing" Target Repos**:
   ```powershell
   ./scripts/vitaminize_repo.ps1 -RepoPath "C:/Path/To/NewRepo" -OrchToken "YOUR_TOKEN"
   ```

   **Linux:**
   ```bash
   ./scripts/vitaminize_repo.sh -r "/path/to/new/repo" -t "YOUR_TOKEN"
   ```
4. **Cloudflare Exposure**: Point `orch.giltech.dev` to `127.0.0.1:9325`.
