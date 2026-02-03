import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


class LLMAuditLogger:
    """Layer 7: Immutable audit trail"""

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Setup dedicated logger with a name unique to the log file to avoid interference in tests
        logger_name = f"llm_audit_{hash(str(log_file))}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False  # Avoid double logging to root

        if not self.logger.handlers:
            # File handler (append-only)
            self.handler = logging.FileHandler(self.log_file, mode="a", encoding="utf-8")
            self.handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
                )
            )
            self.logger.addHandler(self.handler)
        else:
            self.handler = self.logger.handlers[0]

    def _flush(self):
        """Flush the log handler to ensure content is written to disk."""
        if hasattr(self, "handler"):
            self.handler.flush()

    def log_interaction(
        self, interaction_id: str, phase: str, data: Dict, action: str, reason: Optional[str] = None
    ):
        """
        Log an LLM interaction phase.

        Args:
            interaction_id: Unique ID for this interaction
            phase: 'input_sanitization', 'llm_call', 'output_validation', etc.
            data: Relevant data (sanitized, no secrets)
            action: 'ALLOW', 'DENY', 'ABORT'
            reason: Why this action was taken
            detected_secrets_patterns: Dictionary of secret types to regex patterns used for detection.
        """
        log_entry = {
            "interaction_id": interaction_id,
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "reason": reason,
            "data_summary": {
                "input_length": data.get("input_length"),
                "output_length": data.get("output_length"),
                "detected_secrets": data.get("detected_secrets", []),
                "detected_injections": data.get("detected_injections", []),
                "violations": data.get("violations", []),
                "anomalies": data.get("anomalies", []),
            },
        }

        self.logger.info(json.dumps(log_entry))
        self._flush()

    def log_alert(self, severity: str, message: str, details: Dict):
        """Log security alert"""
        alert = {
            "type": "SECURITY_ALERT",
            "severity": severity,  # CRITICAL, HIGH, MEDIUM, LOW
            "message": message,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        }

        self.logger.warning(json.dumps(alert))
        self._flush()
