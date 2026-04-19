"""Tests for tools.gimo_server.security.safe_log.

Covers the explicit per-call helper (:func:`sanitize_for_log`) and the
defense-in-depth filter (:class:`SanitizingLogFilter` /
:func:`install_log_sanitizer`).
"""
from __future__ import annotations

import logging
from io import StringIO

import pytest

from tools.gimo_server.security.safe_log import (
    SanitizingLogFilter,
    install_log_sanitizer,
    sanitize_for_log,
)


# ---------------------------------------------------------------------------
# sanitize_for_log (explicit helper)
# ---------------------------------------------------------------------------

class TestSanitizeForLog:
    def test_strips_crlf_and_tab(self):
        assert sanitize_for_log("a\nb\r\nc\td") == "a b  c d"

    def test_none_returns_empty(self):
        assert sanitize_for_log(None) == ""

    def test_coerces_non_string(self):
        assert sanitize_for_log(42) == "42"
        assert sanitize_for_log(ValueError("boom\nbad")) == "boom bad"

    def test_truncates_long_values(self):
        long = "x" * 1000
        result = sanitize_for_log(long)
        assert len(result) <= 600  # 500 + truncation marker
        assert result.endswith("...[truncated]")


# ---------------------------------------------------------------------------
# SanitizingLogFilter (defense-in-depth)
# ---------------------------------------------------------------------------

class TestSanitizingLogFilter:
    def _make_logger_with_filter(self) -> tuple[logging.Logger, StringIO]:
        """Return a logger whose handler has SanitizingLogFilter installed."""
        buf = StringIO()
        logger = logging.getLogger(f"test.safe_log.{id(buf)}")
        logger.handlers.clear()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.addFilter(SanitizingLogFilter())
        logger.addHandler(handler)
        return logger, buf

    def test_scrubs_fstring_anti_pattern(self):
        logger, buf = self._make_logger_with_filter()
        malicious = "alice\nADMIN LOGIN SUCCESS"
        logger.error(f"user: {malicious}")
        output = buf.getvalue()
        # The forged newline must be replaced — no second line in output.
        assert "\n" not in output.rstrip("\n")
        assert "ADMIN LOGIN SUCCESS" in output  # still there, just inline
        assert "user: alice ADMIN LOGIN SUCCESS" in output

    def test_scrubs_args_positional(self):
        logger, buf = self._make_logger_with_filter()
        logger.error("user: %s", "alice\nADMIN LOGIN")
        output = buf.getvalue()
        assert output.count("\n") == 1  # only the trailing handler newline
        assert "user: alice ADMIN LOGIN" in output

    def test_scrubs_args_mapping(self):
        logger, buf = self._make_logger_with_filter()
        logger.error("user: %(name)s", {"name": "alice\nbad"})
        output = buf.getvalue()
        assert "user: alice bad" in output

    def test_passes_through_clean_values(self):
        logger, buf = self._make_logger_with_filter()
        logger.info("normal message %s", "alice")
        assert "normal message alice" in buf.getvalue()

    def test_non_string_args_untouched(self):
        logger, buf = self._make_logger_with_filter()
        logger.info("count=%d id=%s", 42, None)
        assert "count=42 id=None" in buf.getvalue()

    def test_tab_sanitized(self):
        logger, buf = self._make_logger_with_filter()
        logger.error("field=%s", "col1\tcol2")
        assert "field=col1 col2" in buf.getvalue()


class TestInstallLogSanitizer:
    def test_idempotent(self):
        # Install twice on an isolated logger's handler-equivalent setup.
        # We install on root, then assert no duplicate filters on each handler.
        install_log_sanitizer()
        install_log_sanitizer()
        root = logging.getLogger()
        for handler in root.handlers:
            count = sum(
                1 for f in handler.filters if isinstance(f, SanitizingLogFilter)
            )
            assert count <= 1, f"duplicate filter on {handler!r}"

    def test_installs_on_root_handlers(self):
        # Ensure basicConfig has been called (pytest usually has captureLog).
        if not logging.getLogger().handlers:
            logging.basicConfig()
        install_log_sanitizer()
        root = logging.getLogger()
        assert root.handlers, "root should have at least one handler"
        for handler in root.handlers:
            assert any(
                isinstance(f, SanitizingLogFilter) for f in handler.filters
            ), f"{handler!r} missing SanitizingLogFilter"
