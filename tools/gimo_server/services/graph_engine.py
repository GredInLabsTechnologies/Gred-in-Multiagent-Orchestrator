"""Backward-compatibility shim — imports from decomposed graph/ package."""
from __future__ import annotations

from .graph import GraphEngine

__all__ = ["GraphEngine"]
