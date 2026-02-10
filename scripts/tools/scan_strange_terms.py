"""Repo scanner for potentially problematic / "strange" terms.

Scope:
  - Only scans files tracked by git (uses `git ls-files`).
  - Skips likely-binary files.

Outputs:
  - Writes a text report to tmp/strange_terms_report.txt

This is intentionally conservative: it reports findings, it does not modify files.
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


CODE_EXTS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".sh",
    ".cmd",
    ".bat",
    ".ps1",
    ".psm1",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".md",
}


@dataclass(frozen=True)
class Match:
    path: str
    line_no: int
    line: str


PATTERNS: dict[str, re.Pattern[str]] = {
    # Unicode Bidi control characters (Trojan Source class)
    "bidi_controls": re.compile("[\u202A-\u202E\u2066-\u2069]"),
    # Zero-width joiners & BOM
    "zero_width_or_bom": re.compile("[\u200B\u200C\u200D\uFEFF]"),
    # Emojis (can be OK in docs, but worth knowing)
    "emoji": re.compile("[\U0001F300-\U0001FAFF]"),
    # Some non-ASCII punctuation that often sneaks in via copy/paste
    "unicode_punct": re.compile("[\u2010-\u2015\u2212]"),  # hyphens + minus sign
    # Any non-ascii at all (informational)
    "non_ascii": re.compile("[^\x00-\x7F]"),
    # Placeholder / slang / attention markers
    "weird_terms": re.compile(
        r"\b(TODO|FIXME|HACK|XXX|WIP|WTF|ASDF|QWERTY|LOREM|IPSUM|FOO|BAR|BAZ)\b",
        re.IGNORECASE,
    ),
}


def _git_ls_files() -> list[str]:
    return subprocess.check_output(["git", "ls-files"], text=True).splitlines()


def _is_likely_binary(data: bytes) -> bool:
    # Heuristic: NUL bytes usually means binary.
    return b"\x00" in data[:4096]


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if _is_likely_binary(data):
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace")


def scan(max_matches_per_file: int = 8) -> dict[str, list[Match]]:
    hits: dict[str, list[Match]] = defaultdict(list)

    for rel in _git_ls_files():
        p = Path(rel)
        if p.suffix.lower() not in CODE_EXTS:
            continue
        try:
            text = _read_text(p)
        except OSError:
            continue
        if not text:
            continue

        for cat, rx in PATTERNS.items():
            if not rx.search(text):
                continue
            per_file = 0
            for idx, line in enumerate(text.splitlines()):
                if rx.search(line):
                    hits[cat].append(Match(rel, idx + 1, line.rstrip()[:240]))
                    per_file += 1
                    if per_file >= max_matches_per_file:
                        break

    return hits


def write_report(hits: dict[str, list[Match]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tracked = _git_ls_files()
    scanned = [p for p in tracked if Path(p).suffix.lower() in CODE_EXTS]

    with out_path.open("w", encoding="utf-8", newline="\n") as w:
        w.write(f"TRACKED FILES: {len(tracked)}\n")
        w.write(f"SCANNED (code-ish) FILES: {len(scanned)}\n")

        order = [
            "bidi_controls",
            "zero_width_or_bom",
            "emoji",
            "unicode_punct",
            "non_ascii",
            "weird_terms",
        ]
        for cat in order:
            items = hits.get(cat, [])
            w.write(f"\n== {cat} == {len(items)} matches\n")
            for m in items[:200]:
                w.write(f"{m.path}:{m.line_no}: {m.line}\n")
            if len(items) > 200:
                w.write("... (truncated)\n")


def main() -> int:
    out = Path("tmp/strange_terms_report.txt")
    hits = scan()
    write_report(hits, out)
    print(f"Wrote {out}")
    # Return non-zero if we found the most dangerous class.
    return 2 if hits.get("bidi_controls") or hits.get("zero_width_or_bom") else 0


if __name__ == "__main__":
    raise SystemExit(main())
