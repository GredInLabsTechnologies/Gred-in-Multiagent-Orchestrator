from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from tools.repo_orchestrator.config import TOKENS

security = HTTPBearer(auto_error=False)

def verify_token(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token missing")
    token = credentials.credentials
    if token not in TOKENS:
        raise HTTPException(status_code=403, detail="Invalid token")
    return token
