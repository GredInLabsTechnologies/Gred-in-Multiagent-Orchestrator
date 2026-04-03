"""Shared tool-call parser for all provider adapters.

Extracts tool_calls from LLM text output (JSON-in-text) and normalises them
to OpenAI format. Used by ProviderAdapter base class to guarantee a uniform
contract regardless of provider.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple


def parse_tool_calls_from_text(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract tool_calls JSON blocks from LLM text output.

    Returns (remaining_text, tool_calls_list).
    Supports multiple formats:
    - ```json\n{"tool_calls": [...]}```
    - {"tool_calls": [...]} (bare JSON)
    - Mixed text + JSON
    """
    tool_calls: List[Dict[str, Any]] = []
    remaining = text

    # Pattern 1: JSON code blocks with tool_calls
    json_block_pattern = r'```(?:json)?\s*\n?(\{[^`]*?"tool_calls"[^`]*?\})\s*```'
    matches = list(re.finditer(json_block_pattern, text, re.DOTALL | re.IGNORECASE))

    for match in matches:
        json_str = match.group(1).strip()
        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "tool_calls" in data:
                calls = data["tool_calls"]
                if isinstance(calls, list):
                    for call in calls:
                        if isinstance(call, dict) and "name" in call:
                            tool_calls.append({
                                "id": f"call_{len(tool_calls)}",
                                "type": "function",
                                "function": {
                                    "name": call.get("name", ""),
                                    "arguments": json.dumps(call.get("arguments", {})),
                                },
                            })
                remaining = remaining.replace(match.group(0), "", 1)
        except json.JSONDecodeError:
            continue

    # Pattern 2: Bare JSON objects with tool_calls (no code fence)
    # Use brace-counting instead of regex to handle nested JSON correctly.
    if not tool_calls:
        idx = remaining.find('"tool_calls"')
        if idx != -1:
            # Walk backward to find the opening brace
            start = remaining.rfind("{", 0, idx)
            if start != -1:
                # Walk forward counting braces to find the matching close
                depth = 0
                end = None
                for i in range(start, len(remaining)):
                    if remaining[i] == "{":
                        depth += 1
                    elif remaining[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end is not None:
                    json_str = remaining[start:end]
                    try:
                        data = json.loads(json_str)
                        if isinstance(data, dict) and "tool_calls" in data:
                            calls = data["tool_calls"]
                            if isinstance(calls, list):
                                for call in calls:
                                    if isinstance(call, dict) and "name" in call:
                                        tool_calls.append({
                                            "id": f"call_{len(tool_calls)}",
                                            "type": "function",
                                            "function": {
                                                "name": call.get("name", ""),
                                                "arguments": json.dumps(call.get("arguments", {})),
                                            },
                                        })
                                remaining = remaining[:start] + remaining[end:]
                    except json.JSONDecodeError:
                        pass

    return remaining.strip(), tool_calls
