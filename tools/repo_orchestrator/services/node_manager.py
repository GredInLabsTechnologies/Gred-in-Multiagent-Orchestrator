from typing import Dict, Any
import logging
import asyncio

logger = logging.getLogger("orchestrator.node_manager")

class NodeManager:
    """
    Manages Hardware Nodes and Concurrency Limits.
    Defined in COMPREHENSIVE_INFRASTRUCTURE_REPORT.md
    """
    
    # Defaults based on Infrastructure Report
    _nodes = {
        "ally_x": {
            "name": "ROG Xbox Ally X",
            "max_concurrency": 2,
            "current_load": 0,
            "type": "npu_edge"
        },
        "desktop": {
            "name": "Desktop RTX 3060",
            "max_concurrency": 4,
            "current_load": 0,
            "type": "gpu_workstation"
        }
    }
    
    _semaphores: Dict[str, asyncio.Semaphore] = {}
    
    @classmethod
    def initialize(cls):
        for node_id, config in cls._nodes.items():
            cls._semaphores[node_id] = asyncio.Semaphore(config["max_concurrency"])
            
    @classmethod
    async def acquire_slot(cls, node_id: str):
        if node_id not in cls._semaphores:
            # Fallback for unknown nodes
            cls._semaphores[node_id] = asyncio.Semaphore(1)
            
        await cls._semaphores[node_id].acquire()
        cls._nodes[node_id]["current_load"] += 1
        logger.info(f"Acquired slot on {node_id}. Load: {cls._nodes[node_id]['current_load']}")

    @classmethod
    def release_slot(cls, node_id: str):
        if node_id in cls._semaphores:
            cls._semaphores[node_id].release()
            cls._nodes[node_id]["current_load"] = max(0, cls._nodes[node_id]["current_load"] - 1)
            logger.info(f"Released slot on {node_id}. Load: {cls._nodes[node_id]['current_load']}")

    @classmethod
    def get_nodes_status(cls) -> Dict[str, Any]:
        return cls._nodes

# Auto-initialize on module load (simple for now)
NodeManager.initialize()
