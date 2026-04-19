"""Log-injection defenses (CWE-117, SonarCloud pythonsecurity:S5145).

Two complementary mechanisms live here:

1. :func:`sanitize_for_log` — explicit per-call helper. Coerces to ``str``,
   strips CR/LF/tab, truncates long values. Use when you want the behavior
   inline at a call-site (e.g. when building a structured message or when
   the value may be ``None``).

2. :class:`SanitizingLogFilter` + :func:`install_log_sanitizer` — universal
   defense-in-depth filter installed on the root logger's handlers. It
   strips CR/LF/tab from ``record.msg`` and every element of ``record.args``
   so even f-string logs with user-controlled interpolation cannot forge
   entries. This is the safety net; :func:`sanitize_for_log` remains the
   preferred tool at call-sites where truncation matters.
"""
from __future__ import annotations

import logging
from typing import Any

_MAX_LEN = 500


def sanitize_for_log(value: Any) -> str:
    """Return a log-safe string for ``value``.

    - Coerces to ``str``.
    - Replaces CR/LF/tab with a single space to avoid log forgery.
    - Truncates to ``_MAX_LEN`` characters.
    - ``None`` becomes an empty string.
    """
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    if len(s) > _MAX_LEN:
        s = s[:_MAX_LEN] + "...[truncated]"
    return s


class SanitizingLogFilter(logging.Filter):
    """Defense-in-depth log-injection filter.

    Applied once at boot (see :func:`install_log_sanitizer`). Strips
    CR/LF/tab from ``record.msg`` and every element of ``record.args`` so
    f-string anti-patterns like ``logger.error(f"got {user_input}")``
    cannot inject forged log lines even when the call-site forgets
    :func:`sanitize_for_log`.

    Does NOT truncate — aggressive truncation here would hide stacktraces
    and structured diagnostics. Truncation remains an opt-in at call-sites
    via :func:`sanitize_for_log`.
    """

    _TRANSLATE = str.maketrans({"\r": " ", "\n": " ", "\t": " "})

    @classmethod
    def _scrub(cls, value: Any) -> Any:
        if isinstance(value, str) and ("\r" in value or "\n" in value or "\t" in value):
            return value.translate(cls._TRANSLATE)
        return value

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        record.msg = self._scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub(v) for k, v in record.args.items()}
            else:
                record.args = tuple(self._scrub(a) for a in record.args)
        return True


def install_log_sanitizer() -> None:
    """Install :class:`SanitizingLogFilter` on every root-logger handler.

    Idempotent. Call once from the application entry point, *after*
    ``logging.basicConfig()`` so the handlers exist. New handlers added
    later will NOT be auto-covered — call again if you mutate the root
    handler list at runtime.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, SanitizingLogFilter) for f in handler.filters):
            handler.addFilter(SanitizingLogFilter())


__all__ = [
    "SanitizingLogFilter",
    "install_log_sanitizer",
    "sanitize_for_log",
]
