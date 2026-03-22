"""OpenAI function-calling tool schemas for GIMO agentic chat."""
from __future__ import annotations

from typing import Any, Dict, List

TOOL_RISK_LEVELS: Dict[str, str] = {
    "read_file": "LOW",
    "list_files": "LOW",
    "search_text": "LOW",
    "write_file": "MEDIUM",
    "patch_file": "MEDIUM",
    "search_replace": "MEDIUM",
    "create_dir": "MEDIUM",
    "shell_exec": "HIGH",
}


def get_tool_risk_level(tool_name: str) -> str:
    return TOOL_RISK_LEVELS.get(tool_name, "HIGH")


CHAT_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Always read a file before modifying it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative or absolute path to the file.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-based start line (optional).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-based end line (optional).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in a path. Respects .gitignore.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (default: workspace root).",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum directory depth (default: 2).",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern filter (e.g. '*.py').",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search for a text pattern across files using grep/ripgrep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex or literal search pattern.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: workspace root).",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File glob filter (e.g. '*.ts').",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matches to return (default: 50).",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, creating it if it doesn't exist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative or absolute path to the file.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full content to write.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_replace",
            "description": "Find and replace text in a file. The old_text must appear exactly once.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "The exact text to find (must be unique in the file).",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "The replacement text.",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": "Execute a shell command. Use only when file tools are insufficient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 30).",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file",
            "description": "Apply a unified diff patch to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to patch.",
                    },
                    "diff": {
                        "type": "string",
                        "description": "Unified diff content.",
                    },
                },
                "required": ["path", "diff"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_dir",
            "description": "Create a directory (including parent directories).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the directory to create.",
                    },
                },
                "required": ["path"],
            },
        },
    },
]
