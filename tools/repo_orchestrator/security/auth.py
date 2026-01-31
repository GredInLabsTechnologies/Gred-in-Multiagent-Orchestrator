import time
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from tools.repo_orchestrator.config import TOKENS

security = HTTPBearer(auto_error=False)

def verify_token(_request: Request, credentials: HTTPAuthorizationCredentials | None = Security(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token missing")
    
    # Strip whitespace and validate token is not empty
    token = credentials.credentials.strip() if credentials.credentials else ""
    if not token:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Validate token length (minimum 16 characters for security)
    if len(token) < 16:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    print(f"DEBUG: Checking token '{token}' against tokens: {TOKENS}", flush=True)
    if token not in TOKENS:
        _trigger_panic_for_invalid_token(token)
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


def _trigger_panic_for_invalid_token(token: str) -> None:
    from tools.repo_orchestrator.security import load_security_db, save_security_db, SECURITY_DB_PATH
    import hashlib
    import json

    token_hash = hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()

    try:
        db = json.loads(SECURITY_DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        db = load_security_db()
    db["panic_mode"] = True
    if "recent_events" not in db:
        db["recent_events"] = []
    db["recent_events"].append({
        "type": "PANIC_TRIGGER",
        "timestamp": time.time(),
        "reason": "Invalid authentication attempt",
        "payload_hash": token_hash  # Observability: Hash of the malicious payload
    })
    save_security_db(db)




