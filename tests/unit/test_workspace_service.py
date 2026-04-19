"""Unit tests for WorkspaceService — workspace CRUD, membership, pairing codes.

Tests all 7 invariants:
  INV-W1  Total isolation between workspaces
  INV-W2  A device operates in exactly 1 workspace at a time
  INV-W3  device_mode is per-workspace
  INV-W4  Workspace "default" always exists and cannot be deleted
  INV-W5  Last owner cannot be removed
  INV-S2  No invitation, no workspace (pairing code required)
  INV-S3  Pairing codes are ephemeral (5 min TTL, single-use)
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest

from tools.gimo_server.models.mesh import (
    DeviceMode,
    OperationalState,
    WorkspaceRole,
)
from tools.gimo_server.services.mesh import workspace_service as ws_mod
from tools.gimo_server.services.mesh.workspace_service import WorkspaceService, _safe_id


@pytest.fixture()
def ws_tmpdir() -> Generator[Path, None, None]:
    d = Path(tempfile.mkdtemp(prefix="ws_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def svc(ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceService:
    monkeypatch.setattr(ws_mod, "_BASE", ws_tmpdir / "mesh" / "workspaces")
    monkeypatch.setattr(ws_mod, "_LOCK", ws_tmpdir / "mesh" / ".workspaces.lock")
    return WorkspaceService()


# ═══════════════════════════════════════════════════════════════
# INV-W4 — Default workspace
# ═══════════════════════════════════════════════════════════════

class TestDefaultWorkspace:
    def test_default_created_on_init(self, svc: WorkspaceService):
        """INV-W4: default workspace must exist after init."""
        ws = svc.get_workspace("default")
        assert ws is not None
        assert ws.workspace_id == "default"
        assert ws.name == "Default"

    def test_default_cannot_be_deleted(self, svc: WorkspaceService):
        """INV-W4: delete_workspace('default') must return False."""
        assert svc.delete_workspace("default") is False
        assert svc.get_workspace("default") is not None

    def test_list_includes_default(self, svc: WorkspaceService):
        workspaces = svc.list_workspaces()
        ids = [ws.workspace_id for ws in workspaces]
        assert "default" in ids


# ═══════════════════════════════════════════════════════════════
# Workspace CRUD
# ═══════════════════════════════════════════════════════════════

class TestWorkspaceCRUD:
    def test_create_workspace_no_owner(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="Test WS")
        assert ws.workspace_id.startswith("ws-")
        assert ws.name == "Test WS"
        assert ws.owner_device_id == ""

    def test_create_workspace_with_owner(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="Owned", owner_device_id="dev-1")
        assert ws.owner_device_id == "dev-1"
        # Owner auto-enrolled as member
        member = svc.get_member(ws.workspace_id, "dev-1")
        assert member is not None
        assert member.role == WorkspaceRole.owner

    def test_get_workspace_nonexistent(self, svc: WorkspaceService):
        assert svc.get_workspace("ws-nonexistent") is None

    def test_list_workspaces(self, svc: WorkspaceService):
        svc.create_workspace(name="A")
        svc.create_workspace(name="B")
        workspaces = svc.list_workspaces()
        # default + A + B
        assert len(workspaces) >= 3

    def test_delete_workspace(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="ToDelete")
        assert svc.delete_workspace(ws.workspace_id) is True
        assert svc.get_workspace(ws.workspace_id) is None

    def test_delete_nonexistent(self, svc: WorkspaceService):
        assert svc.delete_workspace("ws-nonexistent") is False


# ═══════════════════════════════════════════════════════════════
# Membership
# ═══════════════════════════════════════════════════════════════

class TestMembership:
    def test_add_and_get_member(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="MemberTest")
        m = svc.add_member(ws.workspace_id, "dev-A")
        assert m.device_id == "dev-A"
        assert m.role == WorkspaceRole.member
        assert m.device_mode == DeviceMode.inference

        fetched = svc.get_member(ws.workspace_id, "dev-A")
        assert fetched is not None
        assert fetched.device_id == "dev-A"

    def test_list_members(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="ListTest", owner_device_id="owner-1")
        svc.add_member(ws.workspace_id, "dev-B")
        members = svc.list_members(ws.workspace_id)
        ids = [m.device_id for m in members]
        assert "owner-1" in ids
        assert "dev-B" in ids

    def test_remove_member(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="RemoveTest", owner_device_id="owner-1")
        svc.add_member(ws.workspace_id, "dev-C")
        assert svc.remove_member(ws.workspace_id, "dev-C") is True
        assert svc.get_member(ws.workspace_id, "dev-C") is None

    def test_remove_nonexistent_member(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="NoMember")
        assert svc.remove_member(ws.workspace_id, "ghost") is False

    def test_get_member_nonexistent(self, svc: WorkspaceService):
        assert svc.get_member("default", "ghost-device") is None


# ═══════════════════════════════════════════════════════════════
# INV-W5 — Last owner protection
# ═══════════════════════════════════════════════════════════════

class TestLastOwnerProtection:
    def test_cannot_remove_sole_owner(self, svc: WorkspaceService):
        """INV-W5: last owner cannot be removed."""
        ws = svc.create_workspace(name="OwnerTest", owner_device_id="sole-owner")
        assert svc.remove_member(ws.workspace_id, "sole-owner") is False
        # Still there
        assert svc.get_member(ws.workspace_id, "sole-owner") is not None

    def test_can_remove_owner_if_another_exists(self, svc: WorkspaceService):
        """INV-W5: if >1 owners, removal is allowed."""
        ws = svc.create_workspace(name="MultiOwner", owner_device_id="owner-A")
        svc.add_member(ws.workspace_id, "owner-B", role=WorkspaceRole.owner)
        assert svc.remove_member(ws.workspace_id, "owner-A") is True
        assert svc.get_member(ws.workspace_id, "owner-A") is None
        # owner-B still there
        assert svc.get_member(ws.workspace_id, "owner-B") is not None


# ═══════════════════════════════════════════════════════════════
# INV-W3 — device_mode per-workspace
# ═══════════════════════════════════════════════════════════════

class TestDeviceModePerWorkspace:
    def test_update_member_mode(self, svc: WorkspaceService):
        """INV-W3: device_mode is per-workspace."""
        ws = svc.create_workspace(name="ModeTest")
        svc.add_member(ws.workspace_id, "dev-X", device_mode=DeviceMode.inference)
        updated = svc.update_member_mode(ws.workspace_id, "dev-X", DeviceMode.utility)
        assert updated is not None
        assert updated.device_mode == DeviceMode.utility

        # Verify persisted
        fetched = svc.get_member(ws.workspace_id, "dev-X")
        assert fetched.device_mode == DeviceMode.utility

    def test_update_mode_nonexistent(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="ModeTest2")
        assert svc.update_member_mode(ws.workspace_id, "ghost", DeviceMode.utility) is None

    def test_different_modes_in_different_workspaces(self, svc: WorkspaceService):
        """INV-W3: same device can have different modes in different workspaces."""
        ws1 = svc.create_workspace(name="WS1")
        ws2 = svc.create_workspace(name="WS2")
        svc.add_member(ws1.workspace_id, "dev-M", device_mode=DeviceMode.inference)
        svc.add_member(ws2.workspace_id, "dev-M", device_mode=DeviceMode.utility)

        m1 = svc.get_member(ws1.workspace_id, "dev-M")
        m2 = svc.get_member(ws2.workspace_id, "dev-M")
        assert m1.device_mode == DeviceMode.inference
        assert m2.device_mode == DeviceMode.utility


# ═══════════════════════════════════════════════════════════════
# get_device_workspaces
# ═══════════════════════════════════════════════════════════════

class TestDeviceWorkspaces:
    def test_get_device_workspaces(self, svc: WorkspaceService):
        ws1 = svc.create_workspace(name="DW1")
        ws2 = svc.create_workspace(name="DW2")
        svc.add_member(ws1.workspace_id, "dev-DW")
        svc.add_member(ws2.workspace_id, "dev-DW")

        memberships = svc.get_device_workspaces("dev-DW")
        ws_ids = [m.workspace_id for m in memberships]
        assert ws1.workspace_id in ws_ids
        assert ws2.workspace_id in ws_ids

    def test_device_with_no_workspaces(self, svc: WorkspaceService):
        assert svc.get_device_workspaces("orphan-device") == []


# ═══════════════════════════════════════════════════════════════
# Pairing Codes — INV-S2, INV-S3
# ═══════════════════════════════════════════════════════════════

class TestPairingCodes:
    def test_generate_pairing_code(self, svc: WorkspaceService):
        """INV-S3: code is 6-digit, has TTL."""
        ws = svc.create_workspace(name="PairTest")
        pc = svc.generate_pairing_code(ws.workspace_id)
        assert pc is not None
        assert len(pc.code) == 6
        assert pc.code.isdigit()
        assert pc.workspace_id == ws.workspace_id
        assert pc.used is False
        assert pc.expires_at > datetime.now(timezone.utc)

    def test_generate_code_nonexistent_workspace(self, svc: WorkspaceService):
        assert svc.generate_pairing_code("ws-nonexistent") is None

    def test_join_with_valid_code(self, svc: WorkspaceService):
        """INV-S2: join via pairing code."""
        ws = svc.create_workspace(name="JoinTest")
        pc = svc.generate_pairing_code(ws.workspace_id)
        membership = svc.join_with_code(pc.code, "dev-join")
        assert membership is not None
        assert membership.workspace_id == ws.workspace_id
        assert membership.device_id == "dev-join"
        assert membership.role == WorkspaceRole.member

    def test_code_is_single_use(self, svc: WorkspaceService):
        """INV-S3: code cannot be reused."""
        ws = svc.create_workspace(name="SingleUse")
        pc = svc.generate_pairing_code(ws.workspace_id)
        svc.join_with_code(pc.code, "dev-first")
        # Second attempt with same code
        result = svc.join_with_code(pc.code, "dev-second")
        assert result is None

    def test_expired_code_rejected(self, svc: WorkspaceService, monkeypatch: pytest.MonkeyPatch):
        """INV-S3: expired codes are rejected."""
        ws = svc.create_workspace(name="ExpiredTest")
        pc = svc.generate_pairing_code(ws.workspace_id)

        # Manually expire the code
        pc.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        pairing_path = ws_mod._BASE / ws.workspace_id / "pairing" / f"{pc.code}.json"
        svc._atomic_write(pairing_path, pc.model_dump_json(indent=2))

        result = svc.join_with_code(pc.code, "dev-late")
        assert result is None

    def test_join_already_member_returns_existing(self, svc: WorkspaceService):
        """If device is already a member, return existing membership."""
        ws = svc.create_workspace(name="AlreadyMember")
        svc.add_member(ws.workspace_id, "dev-existing")
        pc = svc.generate_pairing_code(ws.workspace_id)
        result = svc.join_with_code(pc.code, "dev-existing")
        assert result is not None
        assert result.device_id == "dev-existing"

    def test_join_with_invalid_code(self, svc: WorkspaceService):
        """INV-S2: invalid code => None."""
        result = svc.join_with_code("999999", "dev-invalid")
        assert result is None

    def test_join_with_device_mode(self, svc: WorkspaceService):
        ws = svc.create_workspace(name="ModeJoin")
        pc = svc.generate_pairing_code(ws.workspace_id)
        membership = svc.join_with_code(pc.code, "dev-mode", device_mode=DeviceMode.utility)
        assert membership.device_mode == DeviceMode.utility

    def test_purge_expired_codes(self, svc: WorkspaceService):
        """INV-S3: expired codes are purged."""
        ws = svc.create_workspace(name="PurgeTest")
        pc = svc.generate_pairing_code(ws.workspace_id)

        # Manually expire
        pc.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        pairing_path = ws_mod._BASE / ws.workspace_id / "pairing" / f"{pc.code}.json"
        svc._atomic_write(pairing_path, pc.model_dump_json(indent=2))

        purged = svc._purge_expired_codes(ws.workspace_id)
        assert purged >= 1


# ═══════════════════════════════════════════════════════════════
# INV-W1 — Task queue workspace isolation (via TaskQueue)
# ═══════════════════════════════════════════════════════════════

class TestTaskQueueWorkspaceIsolation:
    """Tests that TaskQueue respects workspace boundaries."""

    @pytest.fixture()
    def registry(self, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import registry as registry_mod
        from tools.gimo_server.services.mesh.registry import MeshRegistry

        monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", ws_tmpdir)
        monkeypatch.setattr(MeshRegistry, "MESH_DIR", ws_tmpdir / "mesh")
        monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", ws_tmpdir / "mesh" / "devices")
        monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", ws_tmpdir / "mesh" / "tokens")
        monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", ws_tmpdir / "mesh" / "thermal_events.jsonl")
        monkeypatch.setattr(MeshRegistry, "LOCK_FILE", ws_tmpdir / "mesh" / ".mesh.lock")
        return MeshRegistry()

    @pytest.fixture()
    def task_queue(self, registry, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import task_queue as tq_mod
        from tools.gimo_server.services.mesh.task_queue import TaskQueue

        monkeypatch.setattr(TaskQueue, "TASKS_DIR", ws_tmpdir / "mesh" / "tasks")
        monkeypatch.setattr(TaskQueue, "LOCK_FILE", ws_tmpdir / "mesh" / ".tasks.lock")
        return TaskQueue(registry)

    def test_create_task_with_workspace(self, task_queue):
        from tools.gimo_server.models.mesh import UtilityTaskType
        task = task_queue.create_task(
            task_type=UtilityTaskType.ping,
            payload={},
            workspace_id="ws-alpha",
        )
        assert task.workspace_id == "ws-alpha"

    def test_create_task_default_workspace(self, task_queue):
        from tools.gimo_server.models.mesh import UtilityTaskType
        task = task_queue.create_task(
            task_type=UtilityTaskType.ping,
            payload={},
        )
        assert task.workspace_id == "default"

    def test_get_assigned_filters_by_workspace(self, task_queue, registry):
        """INV-W1: get_assigned_for_device only returns tasks in device's active workspace."""
        from tools.gimo_server.models.mesh import UtilityTaskType

        # Create device in ws-alpha
        dev = registry.enroll_device("dev-filter", name="Filter", device_mode=DeviceMode.utility)
        registry.approve_device("dev-filter")
        dev = registry.get_device("dev-filter")
        dev.active_workspace_id = "ws-alpha"
        registry.save_device(dev)

        # Create and assign tasks in different workspaces
        t1 = task_queue.create_task(UtilityTaskType.ping, {}, workspace_id="ws-alpha")
        t2 = task_queue.create_task(UtilityTaskType.ping, {}, workspace_id="ws-beta")
        task_queue.assign_task(t1.task_id, "dev-filter")
        task_queue.assign_task(t2.task_id, "dev-filter")

        # Device is in ws-alpha, should only see t1
        assigned = task_queue.get_assigned_for_device("dev-filter")
        assert len(assigned) == 1
        assert assigned[0].task_id == t1.task_id

    def test_auto_assign_respects_workspace(self, task_queue, registry, svc):
        """INV-W1: auto_assign only matches devices to tasks in same workspace."""
        from tools.gimo_server.models.mesh import ConnectionState, OperationalState, UtilityTaskType

        # INV-W6: ws-gamma needs an active Core for task dispatch
        ws = svc.create_workspace(name="Gamma")
        ws_gamma_id = ws.workspace_id
        core = registry.enroll_device("dev-core-g", name="CoreG", device_mode=DeviceMode.server)
        registry.approve_device("dev-core-g")
        core = registry.get_device("dev-core-g")
        core.connection_state = ConnectionState.connected
        core.active_workspace_id = ws_gamma_id
        registry.save_device(core)
        svc.add_member(ws_gamma_id, "dev-core-g", device_mode=DeviceMode.server)

        # Create utility device in ws-gamma
        dev = registry.enroll_device("dev-gamma", name="Gamma", device_mode=DeviceMode.utility)
        registry.approve_device("dev-gamma")
        dev = registry.get_device("dev-gamma")
        dev.active_workspace_id = ws_gamma_id
        dev.operational_state = OperationalState.idle
        registry.save_device(dev)
        svc.add_member(ws_gamma_id, "dev-gamma", device_mode=DeviceMode.utility)

        # Task in ws-gamma (has Core) and ws-other (no Core)
        t_gamma = task_queue.create_task(UtilityTaskType.ping, {}, workspace_id=ws_gamma_id)
        t_other = task_queue.create_task(UtilityTaskType.ping, {}, workspace_id="ws-other")

        assigned = task_queue.auto_assign_pending(mesh_enabled=True)
        # Should assign t_gamma to dev-gamma, not t_other (wrong ws + no Core)
        t_gamma_reloaded = task_queue.get_task(t_gamma.task_id)
        t_other_reloaded = task_queue.get_task(t_other.task_id)
        assert t_gamma_reloaded.assigned_device_id == "dev-gamma"
        assert t_other_reloaded.status.value == "pending"  # Still unassigned


# ═══════════════════════════════════════════════════════════════
# Regression: Path traversal (Bug #6)
# ═══════════════════════════════════════════════════════════════

class TestPathTraversalPrevention:
    def test_safe_id_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            _safe_id("../../etc/passwd")

    def test_safe_id_rejects_dotfile(self):
        with pytest.raises(ValueError):
            _safe_id(".hidden")

    def test_safe_id_rejects_empty(self):
        with pytest.raises(ValueError):
            _safe_id("")

    def test_safe_id_allows_normal_ids(self):
        assert _safe_id("galaxy-s10") == "galaxy-s10"
        assert _safe_id("ws-44ef10237817") == "ws-44ef10237817"
        assert _safe_id("dev_laptop.1") == "dev_laptop.1"

    def test_safe_id_rejects_slashes(self):
        with pytest.raises(ValueError):
            _safe_id("dev/evil")

    def test_get_member_rejects_traversal(self, svc: WorkspaceService):
        with pytest.raises(ValueError):
            svc.get_member("default", "../../etc/passwd")

    def test_add_member_rejects_traversal(self, svc: WorkspaceService):
        with pytest.raises(ValueError):
            svc.add_member("default", "../../../etc/passwd")


# ═══════════════════════════════════════════════════════════════
# Regression: Heartbeat device_mode override (Bug #7)
# ═══════════════════════════════════════════════════════════════

class TestHeartbeatModeProtection:
    """INV-W3: heartbeat must not override workspace-specific device_mode."""

    @pytest.fixture()
    def registry(self, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import registry as registry_mod
        from tools.gimo_server.services.mesh.registry import MeshRegistry

        monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", ws_tmpdir)
        monkeypatch.setattr(MeshRegistry, "MESH_DIR", ws_tmpdir / "mesh")
        monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", ws_tmpdir / "mesh" / "devices")
        monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", ws_tmpdir / "mesh" / "tokens")
        monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", ws_tmpdir / "mesh" / "thermal_events.jsonl")
        monkeypatch.setattr(MeshRegistry, "LOCK_FILE", ws_tmpdir / "mesh" / ".mesh.lock")
        return MeshRegistry()

    def test_heartbeat_preserves_workspace_mode(self, registry, svc: WorkspaceService):
        """When device is in a non-default workspace, heartbeat must not overwrite mode."""
        from tools.gimo_server.models.mesh import HeartbeatPayload

        dev = registry.enroll_device("dev-mode", name="ModeTest", device_mode=DeviceMode.inference)
        registry.approve_device("dev-mode")

        # Simulate: device was activated into a workspace with utility mode
        dev = registry.get_device("dev-mode")
        dev.active_workspace_id = "ws-custom"
        dev.device_mode = DeviceMode.utility  # Set by activate endpoint
        registry.save_device(dev)

        # Heartbeat reports inference (device's own preference)
        hb = HeartbeatPayload(
            device_id="dev-mode",
            device_secret=dev.device_secret,
            device_mode=DeviceMode.inference,  # tries to override
        )
        updated = registry.process_heartbeat(hb)

        # Must keep utility — workspace mode takes precedence
        assert updated.device_mode == DeviceMode.utility

    def test_heartbeat_allows_mode_in_default_workspace(self, registry):
        """When device is in default workspace, heartbeat mode is accepted."""
        from tools.gimo_server.models.mesh import HeartbeatPayload

        dev = registry.enroll_device("dev-def", name="DefMode", device_mode=DeviceMode.inference)
        registry.approve_device("dev-def")

        hb = HeartbeatPayload(
            device_id="dev-def",
            device_secret=dev.device_secret,
            device_mode=DeviceMode.utility,
        )
        updated = registry.process_heartbeat(hb)
        assert updated.device_mode == DeviceMode.utility


# ═══════════════════════════════════════════════════════════════
# Regression: Default workspace membership (Bug #8)
# ═══════════════════════════════════════════════════════════════

class TestDefaultWorkspaceMembership:
    @pytest.fixture()
    def registry(self, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import registry as registry_mod
        from tools.gimo_server.services.mesh.registry import MeshRegistry

        monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", ws_tmpdir)
        monkeypatch.setattr(MeshRegistry, "MESH_DIR", ws_tmpdir / "mesh")
        monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", ws_tmpdir / "mesh" / "devices")
        monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", ws_tmpdir / "mesh" / "tokens")
        monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", ws_tmpdir / "mesh" / "thermal_events.jsonl")
        monkeypatch.setattr(MeshRegistry, "LOCK_FILE", ws_tmpdir / "mesh" / ".mesh.lock")
        return MeshRegistry()

    def test_enrolled_device_is_member_of_default(self, registry, svc: WorkspaceService):
        """Enrolled device must be auto-added to default workspace."""
        registry.enroll_device("dev-auto", name="Auto")
        member = svc.get_member("default", "dev-auto")
        assert member is not None
        assert member.workspace_id == "default"

    def test_device_workspaces_includes_default(self, registry, svc: WorkspaceService):
        registry.enroll_device("dev-ws", name="WS")
        memberships = svc.get_device_workspaces("dev-ws")
        ws_ids = [m.workspace_id for m in memberships]
        assert "default" in ws_ids


# ═══════════════════════════════════════════════════════════════
# Regression: Delete workspace resets devices (Bug #10)
# ═══════════════════════════════════════════════════════════════

class TestDeleteWorkspaceResetsDevices:
    @pytest.fixture()
    def registry(self, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import registry as registry_mod
        from tools.gimo_server.services.mesh.registry import MeshRegistry

        monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", ws_tmpdir)
        monkeypatch.setattr(MeshRegistry, "MESH_DIR", ws_tmpdir / "mesh")
        monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", ws_tmpdir / "mesh" / "devices")
        monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", ws_tmpdir / "mesh" / "tokens")
        monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", ws_tmpdir / "mesh" / "thermal_events.jsonl")
        monkeypatch.setattr(MeshRegistry, "LOCK_FILE", ws_tmpdir / "mesh" / ".mesh.lock")
        return MeshRegistry()

    def test_delete_resets_active_workspace(self, svc: WorkspaceService, registry):
        """Devices in deleted workspace must be reset to default."""
        ws = svc.create_workspace(name="Doomed")
        dev = registry.enroll_device("dev-doom", name="Doom")
        registry.approve_device("dev-doom")

        dev = registry.get_device("dev-doom")
        dev.active_workspace_id = ws.workspace_id
        registry.save_device(dev)

        svc.delete_workspace(ws.workspace_id, registry=registry)

        dev = registry.get_device("dev-doom")
        assert dev.active_workspace_id == "default"


# ═══════════════════════════════════════════════════════════════
# Regression: Remove device cleans memberships (Bug #11)
# ═══════════════════════════════════════════════════════════════

class TestRemoveDeviceCleansMemberships:
    @pytest.fixture()
    def registry(self, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import registry as registry_mod
        from tools.gimo_server.services.mesh.registry import MeshRegistry

        monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", ws_tmpdir)
        monkeypatch.setattr(MeshRegistry, "MESH_DIR", ws_tmpdir / "mesh")
        monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", ws_tmpdir / "mesh" / "devices")
        monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", ws_tmpdir / "mesh" / "tokens")
        monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", ws_tmpdir / "mesh" / "thermal_events.jsonl")
        monkeypatch.setattr(MeshRegistry, "LOCK_FILE", ws_tmpdir / "mesh" / ".mesh.lock")
        return MeshRegistry()

    def test_remove_device_cleans_workspace_members(self, registry, svc: WorkspaceService):
        """Removing a device must clean its membership files."""
        registry.enroll_device("dev-clean", name="Clean")
        ws = svc.create_workspace(name="CleanTest")
        svc.add_member(ws.workspace_id, "dev-clean")

        # Verify membership exists
        assert svc.get_member(ws.workspace_id, "dev-clean") is not None
        assert svc.get_member("default", "dev-clean") is not None

        # Remove device
        registry.remove_device("dev-clean")

        # Memberships should be gone
        assert svc.get_member(ws.workspace_id, "dev-clean") is None
        assert svc.get_member("default", "dev-clean") is None


# ═══════════════════════════════════════════════════════════════
# Regression: join_with_code consumes code for already-member (Bug #12)
# ═══════════════════════════════════════════════════════════════

class TestJoinAlreadyMemberConsumesCode:
    def test_code_consumed_even_for_existing_member(self, svc: WorkspaceService):
        """Code must be consumed even when device is already a member."""
        ws = svc.create_workspace(name="ConsumeTest")
        svc.add_member(ws.workspace_id, "dev-existing")

        pc = svc.generate_pairing_code(ws.workspace_id)
        svc.join_with_code(pc.code, "dev-existing")  # Already member

        # Code must be consumed — second device cannot reuse
        result = svc.join_with_code(pc.code, "dev-second")
        assert result is None


# ═══════════════════════════════════════════════════════════════
# Regression: force_remove_member bypasses INV-W5
# ═══════════════════════════════════════════════════════════════

class TestForceRemoveMember:
    def test_force_remove_sole_owner(self, svc: WorkspaceService):
        """force_remove_member must bypass INV-W5."""
        ws = svc.create_workspace(name="ForceTest", owner_device_id="sole-owner")
        # Normal remove should fail
        assert svc.remove_member(ws.workspace_id, "sole-owner") is False
        # Force remove should succeed
        assert svc.force_remove_member(ws.workspace_id, "sole-owner") is True
        assert svc.get_member(ws.workspace_id, "sole-owner") is None


# ═══════════════════════════════════════════════════════════════
# Regression Round 3: _safe_id rejects instead of stripping (Bug #14)
# ═══════════════════════════════════════════════════════════════

class TestSafeIdRejectsNotStrips:
    def test_rejects_unicode(self):
        with pytest.raises(ValueError):
            _safe_id("设备1")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError):
            _safe_id("my device")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError):
            _safe_id("dev\\evil")

    def test_rejects_colon(self):
        """Windows path separator."""
        with pytest.raises(ValueError):
            _safe_id("C:evil")


# ═══════════════════════════════════════════════════════════════
# Regression Round 3: _atomic_write concurrent safety (Bug #13)
# ═══════════════════════════════════════════════════════════════

class TestAtomicWriteConcurrency:
    def test_atomic_write_uses_unique_temp(self, svc: WorkspaceService, ws_tmpdir: Path):
        """Verify _atomic_write doesn't clobber concurrent writes."""
        target = ws_tmpdir / "test_atomic.json"
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write twice — should not raise even if called rapidly
        svc._atomic_write(target, '{"a": 1}')
        svc._atomic_write(target, '{"a": 2}')
        assert target.read_text(encoding="utf-8") == '{"a": 2}'

    def test_atomic_write_no_leftover_tmp(self, svc: WorkspaceService, ws_tmpdir: Path):
        """No .tmp files should be left behind after successful write."""
        import glob
        target = ws_tmpdir / "test_clean.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        svc._atomic_write(target, '{"clean": true}')
        tmp_files = glob.glob(str(ws_tmpdir / "*.tmp"))
        assert len(tmp_files) == 0


# ═══════════════════════════════════════════════════════════════
# Regression Round 3: task result device validation (Bug #17)
# ═══════════════════════════════════════════════════════════════

class TestTaskResultDeviceValidation:
    """submit_task_result must reject results from wrong device."""

    @pytest.fixture()
    def registry(self, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import registry as registry_mod
        from tools.gimo_server.services.mesh.registry import MeshRegistry

        monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", ws_tmpdir)
        monkeypatch.setattr(MeshRegistry, "MESH_DIR", ws_tmpdir / "mesh")
        monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", ws_tmpdir / "mesh" / "devices")
        monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", ws_tmpdir / "mesh" / "tokens")
        monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", ws_tmpdir / "mesh" / "thermal_events.jsonl")
        monkeypatch.setattr(MeshRegistry, "LOCK_FILE", ws_tmpdir / "mesh" / ".mesh.lock")
        return MeshRegistry()

    @pytest.fixture()
    def task_queue(self, registry, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh.task_queue import TaskQueue

        monkeypatch.setattr(TaskQueue, "TASKS_DIR", ws_tmpdir / "mesh" / "tasks")
        monkeypatch.setattr(TaskQueue, "LOCK_FILE", ws_tmpdir / "mesh" / ".tasks.lock")
        return TaskQueue(registry)

    def test_task_assigned_to_correct_device(self, task_queue, registry):
        """Only the assigned device can submit results."""
        from tools.gimo_server.models.mesh import TaskResult, UtilityTaskType

        task = task_queue.create_task(UtilityTaskType.ping, {})
        task_queue.assign_task(task.task_id, "dev-legit")

        # Legit device can complete
        result = TaskResult(
            task_id=task.task_id,
            device_id="dev-legit",
            status="completed",
            result={"pong": True},
        )
        completed = task_queue.complete_task(result)
        assert completed is not None
        assert completed.status.value == "completed"


# ═══════════════════════════════════════════════════════════════
# Regression Round 4: expire_stale clears device.active_task_id
# ═══════════════════════════════════════════════════════════════

class TestExpireStaleClearsDevice:
    """expire_stale must clear the device's active_task_id when its task times out."""

    @pytest.fixture()
    def registry(self, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import registry as registry_mod
        from tools.gimo_server.services.mesh.registry import MeshRegistry

        monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", ws_tmpdir)
        monkeypatch.setattr(MeshRegistry, "MESH_DIR", ws_tmpdir / "mesh")
        monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", ws_tmpdir / "mesh" / "devices")
        monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", ws_tmpdir / "mesh" / "tokens")
        monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", ws_tmpdir / "mesh" / "thermal_events.jsonl")
        monkeypatch.setattr(MeshRegistry, "LOCK_FILE", ws_tmpdir / "mesh" / ".mesh.lock")
        return MeshRegistry()

    @pytest.fixture()
    def task_queue(self, registry, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh.task_queue import TaskQueue

        monkeypatch.setattr(TaskQueue, "TASKS_DIR", ws_tmpdir / "mesh" / "tasks")
        monkeypatch.setattr(TaskQueue, "LOCK_FILE", ws_tmpdir / "mesh" / ".tasks.lock")
        return TaskQueue(registry)

    def test_expire_clears_device_active_task(self, task_queue, registry):
        from tools.gimo_server.models.mesh import UtilityTaskType

        dev = registry.enroll_device("dev-stuck", name="Stuck", device_mode=DeviceMode.utility)
        registry.approve_device("dev-stuck")

        task = task_queue.create_task(UtilityTaskType.ping, {}, timeout_seconds=1)
        task_queue.assign_task(task.task_id, "dev-stuck")

        # Set device's active_task_id
        dev = registry.get_device("dev-stuck")
        dev.active_task_id = task.task_id
        registry.save_device(dev)

        # Force expiry by backdating assigned_at
        t = task_queue.get_task(task.task_id)
        t.assigned_at = t.assigned_at - timedelta(seconds=60)
        task_queue._save_task(t)

        expired = task_queue.expire_stale()
        assert task.task_id in expired

        dev = registry.get_device("dev-stuck")
        assert dev.active_task_id == ""


# ═══════════════════════════════════════════════════════════════
# Regression Round 4: pairing code input sanitization
# ═══════════════════════════════════════════════════════════════

class TestPairingCodeSanitization:
    def test_join_rejects_non_numeric_code(self, svc: WorkspaceService):
        assert svc.join_with_code("../../x", "dev-x") is None

    def test_join_rejects_too_long_code(self, svc: WorkspaceService):
        assert svc.join_with_code("1234567", "dev-x") is None

    def test_join_rejects_too_short_code(self, svc: WorkspaceService):
        assert svc.join_with_code("123", "dev-x") is None

    def test_join_rejects_empty_code(self, svc: WorkspaceService):
        assert svc.join_with_code("", "dev-x") is None

    def test_join_rejects_alpha_code(self, svc: WorkspaceService):
        assert svc.join_with_code("abcdef", "dev-x") is None


# ═══════════════════════════════════════════════════════════════
# Regression Round 4: _safe_id used for enroll validation
# ═══════════════════════════════════════════════════════════════

class TestEnrollDeviceIdValidation:
    def test_safe_id_rejects_slash_device_id(self):
        with pytest.raises(ValueError):
            _safe_id("../evil")

    def test_safe_id_rejects_null_byte(self):
        with pytest.raises(ValueError):
            _safe_id("dev\x00evil")

    def test_safe_id_accepts_android_style_id(self):
        assert _safe_id("galaxy-s10") == "galaxy-s10"
        assert _safe_id("pixel-7a.local") == "pixel-7a.local"


# ═══════════════════════════════════════════════════════════════
# INV-W6 — No Core, no execution
# ═══════════════════════════════════════════════════════════════

class TestNoCoreNoExecution:
    """INV-W6: workspace without active Core blocks task dispatch."""

    @pytest.fixture()
    def registry(self, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh import registry as registry_mod
        from tools.gimo_server.services.mesh.registry import MeshRegistry

        monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", ws_tmpdir)
        monkeypatch.setattr(MeshRegistry, "MESH_DIR", ws_tmpdir / "mesh")
        monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", ws_tmpdir / "mesh" / "devices")
        monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", ws_tmpdir / "mesh" / "tokens")
        monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", ws_tmpdir / "mesh" / "thermal_events.jsonl")
        monkeypatch.setattr(MeshRegistry, "LOCK_FILE", ws_tmpdir / "mesh" / ".mesh.lock")
        return MeshRegistry()

    @pytest.fixture()
    def task_queue(self, registry, ws_tmpdir: Path, monkeypatch: pytest.MonkeyPatch):
        from tools.gimo_server.services.mesh.task_queue import TaskQueue

        monkeypatch.setattr(TaskQueue, "TASKS_DIR", ws_tmpdir / "mesh" / "tasks")
        monkeypatch.setattr(TaskQueue, "LOCK_FILE", ws_tmpdir / "mesh" / ".tasks.lock")
        return TaskQueue(registry)

    def test_default_workspace_always_has_core(self, svc: WorkspaceService, registry):
        """Default workspace always returns True (central server is Core)."""
        assert svc.has_active_core("default", registry) is True

    def test_workspace_without_server_has_no_core(self, svc: WorkspaceService, registry):
        """Workspace with only inference devices has no Core."""
        ws = svc.create_workspace(name="InferenceOnly")
        dev = registry.enroll_device("dev-inf", name="Inf", device_mode=DeviceMode.inference)
        registry.approve_device("dev-inf")
        dev = registry.get_device("dev-inf")
        from tools.gimo_server.models.mesh import ConnectionState
        dev.connection_state = ConnectionState.connected
        registry.save_device(dev)
        svc.add_member(ws.workspace_id, "dev-inf", device_mode=DeviceMode.inference)

        assert svc.has_active_core(ws.workspace_id, registry) is False

    def test_workspace_with_server_has_core(self, svc: WorkspaceService, registry):
        """Workspace with a connected server device has Core."""
        ws = svc.create_workspace(name="WithServer")
        dev = registry.enroll_device("dev-srv", name="Server", device_mode=DeviceMode.server)
        registry.approve_device("dev-srv")
        dev = registry.get_device("dev-srv")
        from tools.gimo_server.models.mesh import ConnectionState
        dev.connection_state = ConnectionState.connected
        registry.save_device(dev)
        svc.add_member(ws.workspace_id, "dev-srv", device_mode=DeviceMode.server)

        assert svc.has_active_core(ws.workspace_id, registry) is True

    def test_workspace_with_hybrid_has_core(self, svc: WorkspaceService, registry):
        """Workspace with a connected hybrid device has Core."""
        ws = svc.create_workspace(name="WithHybrid")
        dev = registry.enroll_device("dev-hyb", name="Hybrid", device_mode=DeviceMode.hybrid)
        registry.approve_device("dev-hyb")
        dev = registry.get_device("dev-hyb")
        from tools.gimo_server.models.mesh import ConnectionState
        dev.connection_state = ConnectionState.connected
        registry.save_device(dev)
        svc.add_member(ws.workspace_id, "dev-hyb", device_mode=DeviceMode.hybrid)

        assert svc.has_active_core(ws.workspace_id, registry) is True

    def test_workspace_with_offline_server_has_no_core(self, svc: WorkspaceService, registry):
        """Server device that is offline does NOT count as active Core."""
        ws = svc.create_workspace(name="OfflineServer")
        dev = registry.enroll_device("dev-off", name="OffSrv", device_mode=DeviceMode.server)
        registry.approve_device("dev-off")
        # Device stays in approved state, not connected
        svc.add_member(ws.workspace_id, "dev-off", device_mode=DeviceMode.server)

        assert svc.has_active_core(ws.workspace_id, registry) is False

    def test_auto_assign_skips_coreless_workspace(self, svc: WorkspaceService, registry, task_queue):
        """INV-W6: auto_assign must skip tasks in workspaces without Core."""
        from tools.gimo_server.models.mesh import ConnectionState, UtilityTaskType

        ws = svc.create_workspace(name="NoCoreWS")

        # Utility device in ws — connected and idle
        dev = registry.enroll_device("dev-util", name="Util", device_mode=DeviceMode.utility)
        registry.approve_device("dev-util")
        dev = registry.get_device("dev-util")
        dev.connection_state = ConnectionState.connected
        dev.active_workspace_id = ws.workspace_id
        dev.operational_state = OperationalState.idle
        registry.save_device(dev)
        svc.add_member(ws.workspace_id, "dev-util", device_mode=DeviceMode.utility)

        # Create task in the coreless workspace
        task = task_queue.create_task(UtilityTaskType.ping, {}, workspace_id=ws.workspace_id)

        # Auto-assign should NOT assign — no Core in workspace
        assigned = task_queue.auto_assign_pending(mesh_enabled=True)
        assert assigned == 0

        t = task_queue.get_task(task.task_id)
        assert t.status.value == "pending"

    def test_auto_assign_works_with_core_present(self, svc: WorkspaceService, registry, task_queue):
        """Tasks are assigned when workspace has an active Core."""
        from tools.gimo_server.models.mesh import ConnectionState, UtilityTaskType

        ws = svc.create_workspace(name="WithCoreWS")

        # Server device (the Core) — connected
        srv = registry.enroll_device("dev-core", name="Core", device_mode=DeviceMode.server)
        registry.approve_device("dev-core")
        srv = registry.get_device("dev-core")
        srv.connection_state = ConnectionState.connected
        srv.active_workspace_id = ws.workspace_id
        registry.save_device(srv)
        svc.add_member(ws.workspace_id, "dev-core", device_mode=DeviceMode.server)

        # Utility device — connected and idle
        dev = registry.enroll_device("dev-worker", name="Worker", device_mode=DeviceMode.utility)
        registry.approve_device("dev-worker")
        dev = registry.get_device("dev-worker")
        dev.connection_state = ConnectionState.connected
        dev.active_workspace_id = ws.workspace_id
        dev.operational_state = OperationalState.idle
        registry.save_device(dev)
        svc.add_member(ws.workspace_id, "dev-worker", device_mode=DeviceMode.utility)

        # Create task
        task = task_queue.create_task(UtilityTaskType.ping, {}, workspace_id=ws.workspace_id)

        # Auto-assign SHOULD work — Core is present
        assigned = task_queue.auto_assign_pending(mesh_enabled=True)
        assert assigned == 1

        t = task_queue.get_task(task.task_id)
        assert t.assigned_device_id == "dev-worker"


# ═══════════════════════════════════════════════════════════════
# INV-L1 — License binding
# ═══════════════════════════════════════════════════════════════

class TestLicenseBinding:
    """INV-L1: workspaces are bound to the Core license that created them.
    Blocked (not deleted) if the license doesn't match."""

    def test_workspace_created_with_license_hash(self, svc: WorkspaceService, monkeypatch: pytest.MonkeyPatch):
        """Workspace stores hash of current Core license key."""
        monkeypatch.setenv("ORCH_LICENSE_KEY", "test-license-key-12345")
        ws = svc.create_workspace(name="Licensed")
        assert ws.license_key_hash != ""
        # Verify it's a SHA-256 hex digest
        assert len(ws.license_key_hash) == 64

    def test_workspace_licensed_with_matching_key(self, svc: WorkspaceService, monkeypatch: pytest.MonkeyPatch):
        """Workspace is licensed when Core has the same key."""
        monkeypatch.setenv("ORCH_LICENSE_KEY", "my-license-key")
        ws = svc.create_workspace(name="Match")
        assert svc.is_workspace_licensed(ws.workspace_id) is True

    def test_workspace_blocked_with_different_key(self, svc: WorkspaceService, monkeypatch: pytest.MonkeyPatch):
        """Workspace is blocked (not deleted) when Core has a different key."""
        monkeypatch.setenv("ORCH_LICENSE_KEY", "original-key")
        ws = svc.create_workspace(name="WillBlock")

        # Change the Core's license key
        monkeypatch.setenv("ORCH_LICENSE_KEY", "new-different-key")
        assert svc.is_workspace_licensed(ws.workspace_id) is False

        # But workspace still exists — just blocked
        assert svc.get_workspace(ws.workspace_id) is not None

    def test_default_workspace_always_licensed(self, svc: WorkspaceService, monkeypatch: pytest.MonkeyPatch):
        """Default workspace is always licensed regardless of key."""
        monkeypatch.setenv("ORCH_LICENSE_KEY", "any-key")
        assert svc.is_workspace_licensed("default") is True

    def test_no_license_key_allows_all(self, svc: WorkspaceService, monkeypatch: pytest.MonkeyPatch):
        """Debug/test mode: no ORCH_LICENSE_KEY → all workspaces allowed."""
        monkeypatch.setenv("ORCH_LICENSE_KEY", "some-key")
        ws = svc.create_workspace(name="DebugTest")

        # Remove license key (debug mode)
        monkeypatch.delenv("ORCH_LICENSE_KEY", raising=False)
        assert svc.is_workspace_licensed(ws.workspace_id) is True

    def test_legacy_workspace_without_hash_allowed(self, svc: WorkspaceService, monkeypatch: pytest.MonkeyPatch):
        """Legacy workspaces (no hash stored) are allowed for backward compat."""
        # Create without license
        monkeypatch.delenv("ORCH_LICENSE_KEY", raising=False)
        ws = svc.create_workspace(name="Legacy")
        assert ws.license_key_hash == ""

        # Now set a license — legacy workspace should still work
        monkeypatch.setenv("ORCH_LICENSE_KEY", "new-key")
        assert svc.is_workspace_licensed(ws.workspace_id) is True

    def test_license_hash_persisted_to_disk(self, svc: WorkspaceService, monkeypatch: pytest.MonkeyPatch):
        """Hash survives get_workspace (roundtrip through JSON)."""
        monkeypatch.setenv("ORCH_LICENSE_KEY", "persist-test-key")
        ws = svc.create_workspace(name="Persist")
        reloaded = svc.get_workspace(ws.workspace_id)
        assert reloaded.license_key_hash == ws.license_key_hash
        assert reloaded.license_key_hash != ""
