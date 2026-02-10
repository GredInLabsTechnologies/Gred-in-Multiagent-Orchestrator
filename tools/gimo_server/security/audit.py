import logging
import os
import re
from logging.handlers import RotatingFileHandler

from tools.gimo_server.config import (
    AUDIT_LOG_BACKUP_COUNT,
    AUDIT_LOG_MAX_BYTES,
    AUDIT_LOG_PATH,
)

# Redaction Patterns
REDACTION_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{48}"),  # OpenAI
    re.compile(r"ghp_[a-zA-Z0-9]{32,}"),  # GitHub Personal Access Token (variable length)
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS
    re.compile(r"(?i)api[-_]?key['\"]?\s*[:=]\s*['\"]?([a-z0-9]{20,})['\"]?"),  # General API Key
    re.compile(r"\b[A-Za-z0-9_-]{40,}\b"),  # Long base64/urlsafe tokens (40+ chars)
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
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[_audit_handler],
)

from .common import get_safe_actor


def audit_log(
    path: str, ranges: str, res_hash: str, operation: str = "READ", actor: str | None = None
):
    # Redact actor if it's a long token (prevent token leakage in logs)
    safe_actor = get_safe_actor(actor)
    log_msg = (
        f"OP:{operation} | PATH:{path} | RANGE:{ranges} | HASH:{res_hash} | ACTOR:{safe_actor}"
    )
    logging.info(log_msg)


def log_panic(
    correlation_id: str,
    reason: str,
    payload_hash: str,
    actor: str | None = None,
    traceback_str: str | None = None,
):
    """Log a critical system panic with correlation metadata."""
    safe_actor = get_safe_actor(actor)
    msg = (
        f"PANIC | ID:{correlation_id} | HASH:{payload_hash} | REASON:{reason} | ACTOR:{safe_actor}"
    )
    logging.critical(msg)

    if traceback_str:
        logging.error(f"PANIC_TRACE [{correlation_id}]:\n{traceback_str}")
