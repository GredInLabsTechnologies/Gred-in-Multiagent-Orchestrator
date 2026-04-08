"""R18 Change 1 — Pydantic-driven MCP tool registration + import-time drift guard.

This module is the canonical registration helper for MCP tools whose parameter
shape is defined by a Pydantic model (the "bridge tools": governance tools and
native tools that wrap internal services).

It solves R18 Pattern B (bridge↔service drift): FastMCP introspects the decorator
signature at ``@mcp.tool()`` time, so a Pydantic model used only *inside* the
function body is invisible to the published MCP schema. If the two drift, clients
see an incorrect schema until someone runs a targeted test.

Two public surfaces:

1. ``bind(tool_name, input_model)`` — declares that an already-registered MCP
   tool is expected to expose a schema equivalent to ``input_model``. Call this
   at registration time (inside ``register_governance_tools`` etc.).

2. ``assert_no_drift(mcp)`` — iterates every binding and compares the *live*
   FastMCP-published schema field set against the Pydantic model's
   ``model_fields`` keys. On mismatch, raises ``ToolSchemaDriftError`` — the
   server refuses to come up. This is called from the real registration site
   (``mcp_bridge/server.py::_startup_and_run`` after ``_register_native``),
   not from package import, so it runs on the same code path the production
   server actually uses.

3. ``register_pydantic_tool(mcp, *, input_model, name, description, handler)``
   is the **forward path** for NEW tools: it builds a wrapper whose
   ``inspect.Signature`` is derived from ``input_model.model_fields``, so
   FastMCP's introspection sees the canonical schema by construction. The
   wrapper also re-validates with ``input_model(**kwargs)`` at call time as a
   second line of defence (PydanticAI-style).

4. ``build_bridge(mcp_factory, *registrars)`` — canonical bridge-builder.
   Any future code path that constructs a FastMCP instance in-process should
   use this helper so the drift assertion cannot be silently skipped.

SOTA position: none of FastMCP, LangChain ``@tool``, OpenAI Agents SDK, or
PydanticAI asserts schema equality at module/boot time. They validate at
registration or first call. Drift can ship to prod. GIMO breaks the boot.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable, Dict, Type

from pydantic import BaseModel

logger = logging.getLogger("mcp_bridge._register")


class ToolSchemaDriftError(RuntimeError):
    """Raised when a live MCP tool schema diverges from its bound Pydantic model.

    This is a boot-time invariant: if raised during ``assert_no_drift``, the
    server refuses to come up. Callers must fix the drift before the process
    can serve any client.
    """


# Module-level registry: tool_name → Pydantic input model.
# Populated by ``bind()`` at registration time, read by ``assert_no_drift()``
# after the real registration path has finished.
_DRIFT_REGISTRY: Dict[str, Type[BaseModel]] = {}


def bind(tool_name: str, input_model: Type[BaseModel]) -> None:
    """Declare that ``tool_name`` must expose a schema matching ``input_model``.

    Call this right after registering the tool with ``@mcp.tool()``. The
    ``assert_no_drift`` check at the end of the real registration path will
    catch any mismatch before the bridge accepts clients.
    """
    if not isinstance(input_model, type) or not issubclass(input_model, BaseModel):
        raise TypeError(
            f"bind({tool_name!r}, ...): input_model must be a Pydantic BaseModel "
            f"subclass, got {input_model!r}"
        )
    _DRIFT_REGISTRY[tool_name] = input_model


def clear_registry() -> None:
    """Test helper: reset the registry between test cases."""
    _DRIFT_REGISTRY.clear()


def _live_schema_fields(mcp: Any, tool_name: str) -> set[str] | None:
    """Return the set of top-level property names published by FastMCP for a tool.

    Returns ``None`` if the tool is not present in the live registry.
    Uses the private ``_tool_manager._tools`` attribute that the existing
    R17 Cluster D tests already rely on (see ``test_native_tools_r17_cluster_d.py``
    and ``native_inputs.py`` docstring).
    """
    try:
        tool = mcp._tool_manager._tools.get(tool_name)  # type: ignore[attr-defined]
    except AttributeError:
        return None
    if tool is None:
        return None
    params = getattr(tool, "parameters", None)
    if not isinstance(params, dict):
        return None
    props = params.get("properties") or {}
    return set(props.keys())


def _model_schema_fields(input_model: Type[BaseModel]) -> set[str]:
    """Return the top-level property names of a Pydantic model's JSON schema."""
    return set(input_model.model_fields.keys())


def assert_no_drift(mcp: Any) -> None:
    """Assert every bound tool's live schema matches its Pydantic model.

    Raises ``ToolSchemaDriftError`` on the first mismatch, carrying all
    mismatches in the message so a single boot failure reports every drift.
    """
    drifts: list[str] = []
    missing: list[str] = []
    for tool_name, input_model in sorted(_DRIFT_REGISTRY.items()):
        live_fields = _live_schema_fields(mcp, tool_name)
        if live_fields is None:
            missing.append(tool_name)
            continue
        expected_fields = _model_schema_fields(input_model)
        if live_fields != expected_fields:
            drifts.append(
                f"  - {tool_name}: "
                f"live={sorted(live_fields)} vs model={sorted(expected_fields)} "
                f"(extra_in_live={sorted(live_fields - expected_fields)}, "
                f"missing_in_live={sorted(expected_fields - live_fields)})"
            )

    if missing:
        logger.warning(
            "assert_no_drift: %d bound tool(s) not found in live registry "
            "(skipped): %s",
            len(missing),
            missing,
        )

    if drifts:
        raise ToolSchemaDriftError(
            "MCP bridge refuses to boot: Pydantic↔FastMCP schema drift detected "
            f"for {len(drifts)} tool(s):\n" + "\n".join(drifts)
        )

    logger.info(
        "assert_no_drift: OK — %d tool(s) verified drift-free.",
        len(_DRIFT_REGISTRY) - len(missing),
    )


def register_pydantic_tool(
    mcp: Any,
    *,
    input_model: Type[BaseModel],
    name: str,
    description: str,
    handler: Callable[[BaseModel], Awaitable[str]],
) -> None:
    """Register an MCP tool whose signature is derived from a Pydantic model.

    Forward path for NEW tools. Existing tools may keep their hand-written
    signatures and declare their model via ``bind()``; this helper exists so
    that any code added in the future cannot re-introduce the drift class.

    Builds a wrapper whose ``inspect.Signature`` mirrors the model's fields
    (so FastMCP introspection sees the canonical schema), validates with
    ``input_model(**kwargs)`` at call time, and delegates to ``handler(params)``.
    """
    fields = input_model.model_fields
    sig_params: list[inspect.Parameter] = []
    for fname, fi in fields.items():
        is_required = fi.is_required()
        default = inspect.Parameter.empty if is_required else fi.default
        annotation = fi.annotation if fi.annotation is not None else Any
        sig_params.append(
            inspect.Parameter(
                name=fname,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )
    wrapper_sig = inspect.Signature(parameters=sig_params, return_annotation=str)

    async def _wrapper(**kwargs: Any) -> str:
        params = input_model(**kwargs)
        return await handler(params)

    _wrapper.__name__ = name
    _wrapper.__doc__ = description
    _wrapper.__signature__ = wrapper_sig  # type: ignore[attr-defined]
    _wrapper.__annotations__ = {p.name: p.annotation for p in sig_params}
    _wrapper.__annotations__["return"] = str

    mcp.tool(name=name, description=description)(_wrapper)
    bind(name, input_model)


def build_bridge(
    mcp_factory: Callable[[], Any],
    *registrars: Callable[[Any], None],
) -> Any:
    """Canonical bridge-builder. Constructs a FastMCP instance, runs every
    registrar in order, and asserts drift-free before returning.

    Any future code path that builds an in-process FastMCP bridge should use
    this helper so the drift guard cannot be silently skipped. The existing
    ``mcp_bridge/server.py::_startup_and_run`` path is not routed through this
    helper (to keep the diff minimal); it calls ``assert_no_drift`` directly
    after its registration step. Both entry points invoke the same check.
    """
    mcp = mcp_factory()
    for registrar in registrars:
        registrar(mcp)
    assert_no_drift(mcp)
    return mcp
