"""Integration tests for P2 conversational flow — thread mood, proposed_plan, and serialization."""
import json
from pathlib import Path

import pytest

from tools.gimo_server.models.conversation import GimoThread
from tools.gimo_server.services.conversation_service import ConversationService


class TestThreadCreation:
    def test_default_mood_is_neutral(self, test_client, valid_token, tmp_path):
        resp = test_client.post(
            "/ops/threads",
            params={"workspace_root": str(tmp_path), "title": "Test Thread"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["mood"] == "neutral"
        assert data["proposed_plan"] is None

    def test_thread_serializes_mood_and_plan(self, tmp_path):
        thread = GimoThread(workspace_root=str(tmp_path), mood="forensic")
        thread.proposed_plan = {"title": "Test Plan", "tasks": []}

        dumped = json.loads(thread.model_dump_json())
        assert dumped["mood"] == "forensic"
        assert dumped["proposed_plan"]["title"] == "Test Plan"

    def test_thread_round_trip_preserves_p2_fields(self, test_client, valid_token, tmp_path):
        # Create via API so we have an event loop for save_thread
        resp = test_client.post(
            "/ops/threads",
            params={"workspace_root": str(tmp_path), "title": "Round Trip Test"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        thread_id = resp.json()["id"]

        # Patch the JSON file directly to add P2 fields
        thread_path = ConversationService.THREADS_DIR / f"{thread_id}.json"
        data = json.loads(thread_path.read_text(encoding="utf-8"))
        data["mood"] = "creative"
        data["proposed_plan"] = {"title": "Creative Plan", "objective": "Explore", "tasks": []}
        thread_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        loaded = ConversationService.get_thread(thread_id)
        assert loaded is not None
        assert loaded.mood == "creative"
        assert loaded.proposed_plan["title"] == "Creative Plan"


class TestGetThreadEndpoint:
    def test_p2_fields_in_get_response(self, test_client, valid_token, tmp_path):
        # Create thread via API
        create_resp = test_client.post(
            "/ops/threads",
            params={"workspace_root": str(tmp_path), "title": "API Test"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        thread_id = create_resp.json()["id"]

        # Patch JSON to add P2 fields
        thread_path = ConversationService.THREADS_DIR / f"{thread_id}.json"
        data = json.loads(thread_path.read_text(encoding="utf-8"))
        data["mood"] = "guardian"
        data["proposed_plan"] = {"title": "Guard Plan", "objective": "Secure", "tasks": []}
        thread_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        # GET should include P2 fields
        get_resp = test_client.get(
            f"/ops/threads/{thread_id}",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["mood"] == "guardian"
        assert data["proposed_plan"]["title"] == "Guard Plan"

    def test_list_threads_includes_p2_fields(self, test_client, valid_token, tmp_path):
        # Create a thread
        test_client.post(
            "/ops/threads",
            params={"workspace_root": str(tmp_path), "title": "List Test"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )

        list_resp = test_client.get(
            "/ops/threads",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert list_resp.status_code == 200
        threads = list_resp.json()
        assert len(threads) > 0
        # All threads should have mood field
        for t in threads:
            assert "mood" in t
            assert "proposed_plan" in t
