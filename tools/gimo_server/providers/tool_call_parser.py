"""Shared tool-call parser for all provider adapters.

Extracts tool_calls from LLM text output (JSON-in-text) and normalises them
to OpenAI format. Used by ProviderAdapter base class to guarantee a uniform
contract regardless of provider.

Supports formats:
1. {"tool_calls": [...]} in code blocks or bare JSON (original)
2. Bare single object: {"name": "...", "arguments": {...}}
3. Bare array: [{"name": "...", "arguments": {...}}]
4. XML tags: <tool_call>{"name": "...", "arguments": {...}}</tool_call>
5. function_call wrapper: {"function_call": {"name": "...", "arguments": {...}}}
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple


def _normalise_call(call: Dict[str, Any], index: int) -> Dict[str, Any] | None:
    """Convert a raw tool call dict to OpenAI-normalised format."""
    if not isinstance(call, dict) or "name" not in call:
        return None
    args = call.get("arguments", call.get("input", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            pass
    return {
        "id": call.get("id") or f"call_{index}",
        "type": "function",
        "function": {
            "name": call["name"],
            "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
        },
    }


def _extract_json_object(text: str, start: int) -> tuple[str | None, int]:
    """Extract a balanced JSON object starting at `start`. Returns (json_str, end_index)."""
    if start >= len(text) or text[start] != "{":
        return None, start
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
    return None, start


def parse_tool_calls_from_text(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract tool_calls from LLM text output.

    Returns (remaining_text, tool_calls_list).
    Tries formats in order of specificity — first match wins.
    """
    tool_calls: List[Dict[str, Any]] = []
    remaining = text

    # --- Pattern 1: JSON code blocks with "tool_calls" key ---
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
                        norm = _normalise_call(call, len(tool_calls))
                        if norm:
                            tool_calls.append(norm)
                remaining = remaining.replace(match.group(0), "", 1)
        except json.JSONDecodeError:
            continue

    if tool_calls:
        return remaining.strip(), tool_calls

    # --- Pattern 2: Bare JSON with "tool_calls" key (no code fence) ---
    idx = remaining.find('"tool_calls"')
    if idx != -1:
        start = remaining.rfind("{", 0, idx)
        if start != -1:
            json_str, end = _extract_json_object(remaining, start)
            if json_str:
                try:
                    data = json.loads(json_str)
                    if isinstance(data, dict) and "tool_calls" in data:
                        calls = data["tool_calls"]
                        if isinstance(calls, list):
                            for call in calls:
                                norm = _normalise_call(call, len(tool_calls))
                                if norm:
                                    tool_calls.append(norm)
                            remaining = remaining[:start] + remaining[end:]
                except json.JSONDecodeError:
                    pass

    if tool_calls:
        return remaining.strip(), tool_calls

    # --- Pattern 3: XML <tool_call> tags ---
    xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
    xml_matches = list(re.finditer(xml_pattern, remaining, re.DOTALL))
    for match in xml_matches:
        try:
            call = json.loads(match.group(1))
            norm = _normalise_call(call, len(tool_calls))
            if norm:
                tool_calls.append(norm)
                remaining = remaining.replace(match.group(0), "", 1)
        except json.JSONDecodeError:
            continue

    if tool_calls:
        return remaining.strip(), tool_calls

    # --- Pattern 4: "function_call" wrapper ---
    fc_pattern = r'\{[^{}]*"function_call"\s*:\s*\{'
    fc_match = re.search(fc_pattern, remaining)
    if fc_match:
        json_str, end = _extract_json_object(remaining, fc_match.start())
        if json_str:
            try:
                data = json.loads(json_str)
                fc = data.get("function_call", {})
                if isinstance(fc, dict) and "name" in fc:
                    norm = _normalise_call(fc, len(tool_calls))
                    if norm:
                        tool_calls.append(norm)
                        remaining = remaining[:fc_match.start()] + remaining[end:]
            except json.JSONDecodeError:
                pass

    if tool_calls:
        return remaining.strip(), tool_calls

    # --- Pattern 5: Bare JSON array of tool calls ---
    # Look for [{"name": ...}, ...] at the start of a line or after whitespace
    array_pattern = r'\[\s*\{[^[\]]*?"name"\s*:'
    arr_match = re.search(array_pattern, remaining)
    if arr_match:
        # Find matching closing bracket
        bracket_start = arr_match.start()
        depth = 0
        arr_end = None
        for i in range(bracket_start, len(remaining)):
            if remaining[i] == "[":
                depth += 1
            elif remaining[i] == "]":
                depth -= 1
                if depth == 0:
                    arr_end = i + 1
                    break
        if arr_end:
            try:
                arr = json.loads(remaining[bracket_start:arr_end])
                if isinstance(arr, list):
                    for call in arr:
                        norm = _normalise_call(call, len(tool_calls))
                        if norm:
                            tool_calls.append(norm)
                    if tool_calls:
                        remaining = remaining[:bracket_start] + remaining[arr_end:]
            except json.JSONDecodeError:
                pass

    if tool_calls:
        return remaining.strip(), tool_calls

    # --- Pattern 6: Bare single object {"name": "...", "arguments": {...}} ---
    # Most common format from small local models (qwen, llama, etc.)
    single_pattern = r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:'
    single_match = re.search(single_pattern, remaining)
    if single_match:
        json_str, end = _extract_json_object(remaining, single_match.start())
        if json_str:
            try:
                call = json.loads(json_str)
                norm = _normalise_call(call, len(tool_calls))
                if norm:
                    tool_calls.append(norm)
                    remaining = remaining[:single_match.start()] + remaining[end:]
            except json.JSONDecodeError:
                pass

    return remaining.strip(), tool_calls
