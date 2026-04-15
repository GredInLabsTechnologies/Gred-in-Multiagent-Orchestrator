"""GIMO Mesh Agent CLI — entry point for device agents.

Usage:
    python -m tools.gimo_mesh_agent.cli --device-id my-phone --core-url http://192.168.1.100:9325

Environment variables:
    GIMO_DEVICE_ID        Device identifier
    GIMO_DEVICE_NAME      Human-readable name
    GIMO_CORE_URL         GIMO Core server URL
    GIMO_AUTH_TOKEN        Authentication token
    GIMO_HEARTBEAT_INTERVAL  Heartbeat interval in seconds (default: 30)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import uuid

from .config import AgentConfig
from .heartbeat import HeartbeatClient
from .local_control import LocalControlManager
from .thermal import ThermalGuard

logger = logging.getLogger("gimo_mesh_agent")


async def run_agent(config: AgentConfig) -> None:
    """Main agent loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    logger.info("GIMO Mesh Agent starting — device_id=%s", config.device_id)
    logger.info("Core URL: %s", config.core_url)

    # Initialize components. LocalControlManager must be retained: it owns
    # the device-side refusal state (local_control.json) and is handed to the
    # HeartbeatClient so status reporting can reflect local overrides.
    thermal = ThermalGuard(config)
    local_control = LocalControlManager(config.resolved_data_dir)
    heartbeat = HeartbeatClient(config, thermal, local_control=local_control)

    # Determine device mode
    modes = []
    if config.allow_inference:
        modes.append("inference")
    if config.allow_utility:
        modes.append("utility")
    if config.allow_server:
        modes.append("server")
    mode = modes[0] if len(modes) == 1 else "hybrid" if len(modes) > 1 else "utility"
    heartbeat.set_device_mode(mode)

    # Start heartbeat
    await heartbeat.start()

    # Wait for shutdown signal
    stop = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    logger.info("Agent running (mode=%s). Press Ctrl+C to stop.", mode)

    try:
        await stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await heartbeat.stop()
        logger.info("Agent stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="GIMO Mesh Device Agent")
    parser.add_argument("--device-id", default="", help="Device identifier")
    parser.add_argument("--device-name", default="", help="Human-readable device name")
    parser.add_argument("--core-url", default="http://localhost:9325", help="GIMO Core URL")
    parser.add_argument("--token", default="", help="Auth token")
    parser.add_argument("--heartbeat-interval", type=int, default=30, help="Seconds between heartbeats")
    args = parser.parse_args()

    # Build config from CLI args + env vars
    env_config = AgentConfig.from_env()
    config = AgentConfig(
        device_id=args.device_id or env_config.device_id or f"device_{uuid.uuid4().hex[:8]}",
        device_name=args.device_name or env_config.device_name,
        core_url=args.core_url if args.core_url != "http://localhost:9325" else env_config.core_url,
        auth_token=args.token or env_config.auth_token,
        allow_inference=env_config.allow_inference,
        allow_utility=env_config.allow_utility,
        allow_server=env_config.allow_server,
        allow_core_control=env_config.allow_core_control,
        allow_task_execution=env_config.allow_task_execution,
        heartbeat_interval_s=args.heartbeat_interval if args.heartbeat_interval != 30 else env_config.heartbeat_interval_s,
    )

    if not config.auth_token:
        print("ERROR: Auth token required. Use --token or GIMO_AUTH_TOKEN env var.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_agent(config))


if __name__ == "__main__":
    main()
