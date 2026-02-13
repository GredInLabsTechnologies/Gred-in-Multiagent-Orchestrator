import time
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from tools.repo_orchestrator.config import TOKENS

security = HTTPBearer(auto_error=False)

def verify_token(_request: Request, credentials: HTTPAuthorizationCredentials | None = Security(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token missing")
    token = credentials.credentials
    if token not in TOKENS:
        # Trigger panic mode on invalid authentication
        from tools.repo_orchestrator.security import load_security_db, save_security_db
        db = load_security_db()
        db["panic_mode"] = True
        if "recent_events" not in db:
            db["recent_events"] = []
        db["recent_events"].append({
            "type": "PANIC_TRIGGER",
            "timestamp": time.time(),
            "reason": "Invalid authentication attempt"
        })
        save_security_db(db)
        raise HTTPException(status_code=401, detail="Invalid token")
    return token

