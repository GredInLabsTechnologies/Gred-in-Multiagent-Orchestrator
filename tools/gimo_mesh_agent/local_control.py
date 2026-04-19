"""Local control state — device-side refusal has absolute precedence.

The user on the physical device can always:
- Disable core control (refuse orchestrator commands)
- Disable task execution (stop accepting work)
- Change device mode
- Force disconnect

These overrides are NON-BYPASSABLE by the orchestrator.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger("gimo_mesh_agent.local_control")


@dataclass
class LocalControlState:
    allow_core_control: bool = True
    allow_task_execution: bool = True
    allow_inference: bool = True
    allow_utility: bool = True
    allow_server: bool = False
    paused: bool = False

    def can_accept_task(self) -> bool:
        return self.allow_core_control and self.allow_task_execution and not self.paused


class LocalControlManager:
    """Persists local control state to disk.

    State file: <data_dir>/local_control.json
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "local_control.json"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    @property
    def state(self) -> LocalControlState:
        return self._state

    def update(self, **kwargs) -> LocalControlState:
        for key, value in kwargs.items():
            if hasattr(self._state, key):
                setattr(self._state, key, value)
        self._save()
        logger.info("Local control updated: %s", kwargs)
        return self._state

    def _load(self) -> LocalControlState:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                return LocalControlState(**data)
            except Exception:
                logger.warning("Failed to load local control state, using defaults")
        return LocalControlState()

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(asdict(self._state), indent=2),
            encoding="utf-8",
        )
