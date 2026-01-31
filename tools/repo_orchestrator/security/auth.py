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
        # Trigger panic mode on invalid authentication
        from tools.repo_orchestrator.security import load_security_db, save_security_db
        import hashlib
        
        token_hash = hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()
        
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
        raise HTTPException(status_code=401, detail="Invalid token")
    return token

