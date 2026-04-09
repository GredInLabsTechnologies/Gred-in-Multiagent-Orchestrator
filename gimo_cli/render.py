"""Declarative CLI response renderer.

Commands declare WHAT to render (columns, title, empty message).
This module handles HOW (unwrapping, table building, empty states).
One function, zero per-command rendering logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from rich.table import Table

from gimo_cli import console
from gimo_cli.stream import emit_output


@dataclass
class TableSpec:
    title: str
    columns: list[str]
    unwrap: Optional[str] = None
    sections: dict[str, "TableSpec"] = field(default_factory=dict)
    empty_msg: str = "No data available."
    summary: Optional[Callable[[dict], str]] = None


def render_response(
    payload: Any,
    spec: TableSpec,
    *,
    json_output: bool = False,
) -> None:
    """Render an API response using a declarative TableSpec."""
    if json_output:
        emit_output(payload, json_output=True)
        return

    # Multi-section responses (analytics, provider models)
    if spec.sections and isinstance(payload, dict):
        any_data = False
        for key, sub_spec in spec.sections.items():
            items = payload.get(key, [])
            if items and isinstance(items, list):
                any_data = True
                _render_table(items, sub_spec)
        if not any_data:
            console.print(f"[dim]{spec.empty_msg}[/dim]")
        if spec.summary:
            console.print(spec.summary(payload))
        return

    # Unwrap wrapped responses ({"items": [...], "count": N})
    data = payload
    if spec.unwrap and isinstance(payload, dict):
        data = payload.get(spec.unwrap, [])

    # Normalize to list
    if isinstance(data, dict):
        data = [data] if data else []

    if not isinstance(data, list) or not data:
        console.print(f"[dim]{spec.empty_msg}[/dim]")
        return

    _render_table(data, spec)


def _render_table(items: list, spec: TableSpec) -> None:
    table = Table(title=spec.title, show_header=True)
    for col in spec.columns:
        table.add_column(col.replace("_", " ").title(), style="cyan")
    for item in items:
        if isinstance(item, dict):
            table.add_row(*(str(item.get(c, ""))[:60] for c in spec.columns))
    console.print(table)


# ── TableSpec registry ──────────────────────────────────────────

FORECAST = TableSpec(
    title="Budget Forecast",
    columns=["scope", "current_spend", "limit", "remaining_pct", "burn_rate_hourly", "alert_level"],
    empty_msg="No forecast data yet. Configure budgets: gimo mastery config",
)

ANALYTICS = TableSpec(
    title="Cost Analytics",
    columns=[],
    sections={
        "by_model": TableSpec(title="Cost by Model", columns=["model", "total_cost", "call_count"]),
        "by_provider": TableSpec(title="Cost by Provider", columns=["provider", "total_cost"]),
    },
    empty_msg="No analytics data yet.",
    summary=lambda p: f"[dim]Total savings: ${p.get('total_savings', 0):.4f}[/dim]",
)

TRACES = TableSpec(
    title="Traces",
    columns=["trace_id", "status", "duration_ms"],
    unwrap="items",
    empty_msg="No traces recorded yet.",
)

PROVIDER_MODELS = TableSpec(
    title="Provider Models",
    columns=[],
    sections={
        "installed_models": TableSpec(title="Installed Models", columns=["id", "quality_tier", "context_window"]),
        "available_models": TableSpec(title="Available Models", columns=["id", "quality_tier"]),
    },
    empty_msg="No models cataloged for this provider.",
)

TRUST_STATUS = TableSpec(
    title="Trust Dimensions",
    columns=["dimension", "score", "state"],
    unwrap="entries",
    empty_msg="No trust data yet. Trust builds as you use GIMO.",
)
