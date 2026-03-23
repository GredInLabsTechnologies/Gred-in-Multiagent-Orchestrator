"""OpenAI function-calling tool schemas for GIMO agentic chat.

P2: Added meta-tools for conversational planning (ask_user, propose_plan, web_search).
"""
from __future__ import annotations

from typing import Any, Dict, List

TOOL_RISK_LEVELS: Dict[str, str] = {
    # File operations
    "read_file": "LOW",
    "list_files": "LOW",
    "search_text": "LOW",
    "write_file": "MEDIUM",
    "patch_file": "MEDIUM",
    "search_replace": "MEDIUM",
    "create_dir": "MEDIUM",
    "shell_exec": "HIGH",
    # P2: Meta-tools
    "ask_user": "LOW",
    "propose_plan": "LOW",
    "web_search": "LOW",
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
    # ── P2: Meta-Tools for Conversational Planning ───────────────────────────
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user a clarifying question before proceeding. "
                "Use this when you need more information to complete the task correctly. "
                "The loop will pause until the user responds."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user.",
                    },
                    "options": {
                        "type": "array",
                        "description": "Optional list of suggested answers (e.g., ['Python', 'JavaScript', 'Both']).",
                        "items": {"type": "string"},
                    },
                    "context": {
                        "type": "string",
                        "description": "Why you're asking this question (helps the user understand).",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_plan",
            "description": (
                "Propose an execution plan for a complex task. "
                "Use this when the task requires 3+ file changes, structural refactors, "
                "or new project setup. Include rationale for why you chose each mood and model. "
                "The loop will pause for user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Plan title (e.g., 'Engineering Calculator Implementation').",
                    },
                    "objective": {
                        "type": "string",
                        "description": "High-level goal of the plan.",
                    },
                    "tasks": {
                        "type": "array",
                        "description": "List of tasks to execute in dependency order.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Unique task ID (e.g., 't1')."},
                                "title": {"type": "string", "description": "Task title."},
                                "description": {"type": "string", "description": "What this task does."},
                                "depends_on": {
                                    "type": "array",
                                    "description": "IDs of tasks that must complete first.",
                                    "items": {"type": "string"},
                                },
                                "agent_mood": {
                                    "type": "string",
                                    "description": "Mood for this task (neutral, forensic, executor, dialoger, creative, guardian, mentor).",
                                },
                                "agent_rationale": {
                                    "type": "string",
                                    "description": "WHY you chose this mood and model for this task.",
                                },
                                "model": {
                                    "type": "string",
                                    "description": "Model to use ('auto' or specific like 'gpt-4o').",
                                },
                            },
                            "required": ["id", "title", "description", "agent_mood", "agent_rationale"],
                        },
                    },
                },
                "required": ["title", "objective", "tasks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for technical information, documentation, or best practices. "
                "Use this when you need up-to-date information beyond your training data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]
