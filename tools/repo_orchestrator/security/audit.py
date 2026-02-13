import os
import re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path
from tools.repo_orchestrator.config import (
    AUDIT_LOG_PATH,
    AUDIT_LOG_MAX_BYTES,
    AUDIT_LOG_BACKUP_COUNT,
)

# Redaction Patterns
REDACTION_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{48}"),         # OpenAI
    re.compile(r"ghp_[a-zA-Z0-9]{32,}"),       # GitHub Personal Access Token (variable length)
    re.compile(r"AKIA[0-9A-Z]{16}"),            # AWS
    re.compile(r"(?i)api[-_]?key['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9]{20,})['\"]?"), # General API Key
]

def redact_sensitive_data(content: str) -> str:
    for pattern in REDACTION_PATTERNS:
        content = pattern.sub("[REDACTED]", content)
    return content

# Audit Logger
os.makedirs(AUDIT_LOG_PATH.parent, exist_ok=True)
_audit_handler = RotatingFileHandler(
    AUDIT_LOG_PATH,
    maxBytes=AUDIT_LOG_MAX_BYTES,
    backupCount=AUDIT_LOG_BACKUP_COUNT,
    encoding="utf-8",
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[_audit_handler],
)

def audit_log(path: str, ranges: str, res_hash: str, operation: str = "READ", actor: str | None = None):
    log_msg = f"OP:{operation} | PATH:{path} | RANGE:{ranges} | HASH:{res_hash} | ACTOR:{actor or 'unknown'}"
    logging.info(log_msg)
