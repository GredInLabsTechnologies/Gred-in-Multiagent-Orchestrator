from __future__ import annotations
import json
import os
from typing import List, Optional
from .contracts import JournalEntry

class RunJournal:
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self._entries: List[JournalEntry] = []

    def append(self, entry: JournalEntry) -> None:
        self._entries.append(entry)
        self._persist_entry(entry)

    def _persist_entry(self, entry: JournalEntry) -> None:
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "a") as f:
            f.write(entry.model_dump_json() + "\n")

    def load(self) -> List[JournalEntry]:
        if not os.path.exists(self.storage_path):
            return []
        
        self._entries = []
        with open(self.storage_path, "r") as f:
            for line in f:
                if line.strip():
                    self._entries.append(JournalEntry.model_validate_json(line))
        return self._entries

    def get_step(self, step_id: str) -> Optional[JournalEntry]:
        for entry in self._entries:
            if entry.step_id == step_id:
                return entry
        return None

    def replay_from(self, step_id: str) -> List[JournalEntry]:
        """Returns entries starting from the specified step_id."""
        found = False
        replay_entries = []
        for entry in self._entries:
            if entry.step_id == step_id:
                found = True
            if found:
                replay_entries.append(entry)
        return replay_entries

    def snapshot(self, max_entries: int = 100) -> None:
        """Compact entries into a snapshot if they exceed max_entries."""
        if len(self._entries) <= max_entries:
            return
            
        snapshot_path = f"{self.storage_path}.snapshot"
        with open(snapshot_path, "w") as f:
            json.dump([e.model_dump() for e in self._entries[:-10]], f)
        
        # Keep only the last 10 entries in the active log
        self._entries = self._entries[-10:]
        with open(self.storage_path, "w") as f:
            for entry in self._entries:
                f.write(entry.model_dump_json() + "\n")
