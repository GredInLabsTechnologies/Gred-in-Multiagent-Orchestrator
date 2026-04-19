"""GIMO Mesh Agent Lite — standalone agent for Android/Termux.

No psutil dependency. Uses android_metrics.py for sensor data.
Sends heartbeats to GIMO server over WiFi.

Usage:
  python mesh_agent_lite.py \
    --core-url http://192.168.0.49:9325 \
    --token <auth_token> \
    --device-id galaxy-s10 \
    --device-secret <secret> \
    --interval 30
"""

from __future__ import annotations

import argparse
import json
import signal
import time
import urllib.request
import urllib.error

from android_metrics import collect_all, get_soc_info

# Fatal HTTP codes — stop retrying
_FATAL_CODES = {401, 403}
_MAX_CONSECUTIVE_FAILURES = 10
_BACKOFF_BASE = 2.0
_BACKOFF_MAX = 300.0  # 5 min cap


def send_heartbeat(
    core_url: str,
    token: str,
    device_id: str,
    device_secret: str,
    metrics: dict,
    model_loaded: str = "",
    inference_endpoint: str = "",
) -> tuple[dict | None, int]:
    """POST heartbeat to GIMO server. Returns (body, http_code)."""
    payload = {
        "device_id": device_id,
        "device_secret": device_secret,
        "device_class": "smartphone",
        "soc_model": metrics.get("soc_model", ""),
        "soc_vendor": metrics.get("soc_vendor", ""),
        "cpu_temp_c": metrics.get("cpu_temp_c", -1.0),
        "gpu_temp_c": metrics.get("gpu_temp_c", -1.0),
        "battery_percent": metrics.get("battery_percent", -1.0),
        "battery_temp_c": metrics.get("battery_temp_c", -1.0),
        "battery_charging": metrics.get("battery_charging", False),
        "cpu_percent": metrics.get("cpu_percent", 0.0),
        "ram_percent": metrics.get("ram_percent", 0.0),
        "health_score": 100.0,
        "thermal_throttled": False,
        "thermal_locked_out": False,
        "model_loaded": model_loaded,
        "inference_endpoint": inference_endpoint,
        "max_model_params_b": 3.09 if model_loaded else 0.0,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{core_url}/ops/mesh/heartbeat",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return body, 200
    except urllib.error.HTTPError as e:
        msg = ""
        try:
            msg = e.read().decode()[:200]
        except Exception:
            pass
        print(f"[heartbeat] HTTP {e.code}: {msg}")
        return None, e.code
    except Exception as e:
        print(f"[heartbeat] Error: {e}")
        return None, 0


def main():
    parser = argparse.ArgumentParser(description="GIMO Mesh Agent Lite")
    parser.add_argument("--core-url", default="http://192.168.0.49:9325")
    parser.add_argument("--token", required=True)
    parser.add_argument("--device-id", default="")
    parser.add_argument("--device-secret", default="")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--model-loaded", default="", help="Name of loaded model (e.g. qwen2.5:3b)")
    parser.add_argument("--inference-endpoint", default="", help="Local inference URL (e.g. http://0.0.0.0:8080)")
    args = parser.parse_args()

    device_id = args.device_id
    if not device_id:
        soc = get_soc_info()
        device_id = soc.get("device_model", "unknown").lower().replace(" ", "-")

    running = True

    def _stop(sig, frame):
        nonlocal running
        print("\n[agent] Shutting down...")
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(f"[agent] GIMO Mesh Agent Lite")
    print(f"[agent] Device: {device_id}")
    print(f"[agent] Core: {args.core_url}")
    print(f"[agent] Interval: {args.interval}s")
    print(f"[agent] Press Ctrl+C to stop")
    print()

    # Initial metrics
    metrics = collect_all()
    print(f"[agent] SoC: {metrics['soc_model']} ({metrics['soc_vendor']})")
    print(f"[agent] RAM: {metrics['ram_total_mb']}MB ({metrics['ram_percent']}% used)")
    print(f"[agent] Battery: {metrics['battery_percent']}% @ {metrics['battery_temp_c']}°C")
    print()

    hb_count = 0
    consecutive_failures = 0
    while running:
        metrics = collect_all()
        result, code = send_heartbeat(
            args.core_url, args.token, device_id, args.device_secret, metrics,
            model_loaded=args.model_loaded,
            inference_endpoint=args.inference_endpoint,
        )

        hb_count += 1

        # Fatal error — stop agent
        if code in _FATAL_CODES:
            print(f"[agent] FATAL: HTTP {code} — authentication failed. Stopping agent.")
            print(f"[agent] Check your --token and --device-secret values.")
            break

        if result:
            consecutive_failures = 0
            state = result.get("connection_state", "?")
            print(f"[hb #{hb_count}] OK — state={state} | "
                  f"cpu={metrics['cpu_percent']}% ram={metrics['ram_percent']}% "
                  f"bat={metrics['battery_percent']}%/{metrics['battery_temp_c']}°C")
        else:
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                print(f"[agent] {_MAX_CONSECUTIVE_FAILURES} consecutive failures — stopping.")
                break
            print(f"[hb #{hb_count}] FAILED ({consecutive_failures}/{_MAX_CONSECUTIVE_FAILURES})")

        # Backoff on failures, normal interval on success
        if consecutive_failures > 0:
            wait = min(_BACKOFF_BASE ** consecutive_failures, _BACKOFF_MAX)
            print(f"[agent] Retrying in {wait:.0f}s (backoff)")
        else:
            wait = args.interval

        # Sleep in small chunks so Ctrl+C is responsive
        for _ in range(int(wait * 2)):
            if not running:
                break
            time.sleep(0.5)

    print("[agent] Stopped.")


if __name__ == "__main__":
    main()
