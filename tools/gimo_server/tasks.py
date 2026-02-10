import asyncio
import logging

from tools.gimo_server.services.snapshot_service import SnapshotService

logger = logging.getLogger("orchestrator")


async def snapshot_cleanup_loop():
    """Background task to delete old snapshots every minute."""
    while True:
        try:
            await asyncio.sleep(60)
            SnapshotService.cleanup_old_snapshots()
        except asyncio.CancelledError:
            logger.debug("Snapshot cleanup loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in snapshot cleanup: {str(e)}")
            await asyncio.sleep(10)
