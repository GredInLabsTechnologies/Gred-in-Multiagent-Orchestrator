from pathlib import Path
from typing import List, Tuple


class ScopeLimiter:
    """Layer 2: Limit what the LLM can see"""

    MAX_FILES = 10
    MAX_TOTAL_TOKENS = 8000  # ~6k tokens for GPT-4, leaving room for response
    MAX_LINES_PER_FILE = 500
    MAX_BYTES_PER_FILE = 100_000  # 100KB

    ALLOWED_EXTENSIONS = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".md",
        ".txt",
        ".yaml",
        ".json",
        ".yml",
    }
    DENIED_PATHS = {".env", "secrets.yaml", "credentials.json", ".ssh/", ".aws/", "node_modules/"}

    @classmethod
    def filter_files(cls, file_paths: List[Path]) -> Tuple[List[Path], List[str]]:
        """
        Filter files based on security policies.
        Returns: (allowed_files, denial_reasons)
        """
        allowed = []
        denied = []

        for path in file_paths:
            path_str = str(path).replace("\\", "/")  # Normalize for cross-platform check

            # Check denied paths FIRST
            if any(denied_part in path_str for denied_part in cls.DENIED_PATHS):
                denied.append(f"{path}: Path in denylist")
                continue

            # Check extension
            if path.suffix not in cls.ALLOWED_EXTENSIONS:
                denied.append(f"{path}: Extension not allowed ({path.suffix})")
                continue

            # Check file presence and size
            if path.exists():
                if path.stat().st_size > cls.MAX_BYTES_PER_FILE:
                    denied.append(f"{path}: File too large ({path.stat().st_size} bytes)")
                    continue

            allowed.append(path)

            # Stop if max files reached
            if len(allowed) >= cls.MAX_FILES:
                if len(file_paths) > cls.MAX_FILES:
                    denied.append(f"Max files limit reached ({cls.MAX_FILES})")
                break

        return allowed, denied

    @classmethod
    def truncate_content(cls, content: str, max_tokens: int = None) -> str:
        """
        Truncate content to max tokens (approximate: 1 token ≈ 4 chars)
        """
        max_tokens = max_tokens or cls.MAX_TOTAL_TOKENS
        max_chars = max_tokens * 4

        if len(content) <= max_chars:
            return content

        # Truncate and add marker
        truncated = content[:max_chars]
        truncated += "\n\n[... CONTENT TRUNCATED FOR SAFETY ...]"
        return truncated

    @classmethod
    def check_line_limit(cls, content: str) -> bool:
        """Check if content exceeds line limit"""
        return len(content.splitlines()) <= cls.MAX_LINES_PER_FILE
