#!/bin/bash
# GIMO Mesh Node — Startup script for Android (adb shell or Termux)
# Launches llama-server + mesh_agent_lite in a single script.
#
# Usage (from adb shell):
#   cd /data/local/tmp && bash start_mesh_node.sh
#
# Usage (from Termux):
#   bash ~/start_mesh_node.sh
#
# Environment variables (or edit defaults below):
#   GIMO_CORE_URL    — GIMO server URL (default: http://192.168.0.49:9325)
#   GIMO_TOKEN       — Auth token (required)
#   GIMO_DEVICE_ID   — Device ID (default: galaxy-s10)
#   GIMO_DEVICE_SECRET — Device secret (required)
#   LLAMA_MODEL      — Path to GGUF model file
#   LLAMA_PORT       — Inference server port (default: 8080)
#   LLAMA_THREADS    — Generation threads (default: 4)
#   LLAMA_CTX        — Context size (default: 2048)

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────
GIMO_CORE_URL="${GIMO_CORE_URL:-http://192.168.0.49:9325}"
GIMO_DEVICE_ID="${GIMO_DEVICE_ID:-galaxy-s10}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
LLAMA_THREADS="${LLAMA_THREADS:-4}"
LLAMA_CTX="${LLAMA_CTX:-2048}"
LLAMA_BATCH_THREADS="${LLAMA_BATCH_THREADS:-8}"

# ── Resolve paths ───────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Detect runtime: adb shell vs Termux
if [ -d "/data/data/com.termux" ] && [ -w "$HOME" ]; then
    RUNTIME="termux"
    BASE_DIR="$HOME"
else
    RUNTIME="adb-shell"
    BASE_DIR="/data/local/tmp"
fi

LLAMA_SERVER="$BASE_DIR/llama-server"
LLAMA_MODEL="${LLAMA_MODEL:-$BASE_DIR/qwen2.5-3b-instruct.gguf}"
AGENT_SCRIPT="$BASE_DIR/mesh_agent_lite.py"
METRICS_SCRIPT="$BASE_DIR/android_metrics.py"

echo "=== GIMO Mesh Node ==="
echo "Runtime:    $RUNTIME"
echo "Base dir:   $BASE_DIR"
echo "Model:      $LLAMA_MODEL"
echo "Threads:    $LLAMA_THREADS (batch: $LLAMA_BATCH_THREADS)"
echo "Context:    $LLAMA_CTX"
echo "Port:       $LLAMA_PORT"
echo "Core URL:   $GIMO_CORE_URL"
echo "Device ID:  $GIMO_DEVICE_ID"
echo ""

# ── Validate ────────────────────────────────────────────────
missing=""
[ ! -f "$LLAMA_SERVER" ] && missing="$missing llama-server"
[ ! -f "$LLAMA_MODEL" ] && missing="$missing model"
[ -z "${GIMO_TOKEN:-}" ] && missing="$missing GIMO_TOKEN"
[ -z "${GIMO_DEVICE_SECRET:-}" ] && missing="$missing GIMO_DEVICE_SECRET"

if [ -n "$missing" ]; then
    echo "ERROR: Missing:$missing"
    echo ""
    echo "Required env vars: GIMO_TOKEN, GIMO_DEVICE_SECRET"
    echo "Required files: $LLAMA_SERVER, $LLAMA_MODEL"
    exit 1
fi

# ── Detect local IP for inference endpoint ──────────────────
LOCAL_IP=""
if command -v ip > /dev/null 2>&1; then
    LOCAL_IP=$(ip route get 1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
elif command -v ifconfig > /dev/null 2>&1; then
    LOCAL_IP=$(ifconfig wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | sed 's/addr://')
fi
[ -z "$LOCAL_IP" ] && LOCAL_IP="0.0.0.0"
INFERENCE_ENDPOINT="http://${LOCAL_IP}:${LLAMA_PORT}"
echo "Inference:  $INFERENCE_ENDPOINT"
echo ""

# ── Cleanup on exit ─────────────────────────────────────────
LLAMA_PID=""
AGENT_PID=""

cleanup() {
    echo ""
    echo "[shutdown] Stopping processes..."
    [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null
    [ -n "$LLAMA_PID" ] && kill "$LLAMA_PID" 2>/dev/null
    wait 2>/dev/null
    echo "[shutdown] Done."
}
trap cleanup EXIT INT TERM

# ── Start llama-server ──────────────────────────────────────
echo "[llama] Starting inference server..."
export LD_LIBRARY_PATH="$BASE_DIR:${LD_LIBRARY_PATH:-}"
"$LLAMA_SERVER" \
    -m "$LLAMA_MODEL" \
    -c "$LLAMA_CTX" \
    --host 0.0.0.0 \
    --port "$LLAMA_PORT" \
    -t "$LLAMA_THREADS" \
    -tb "$LLAMA_BATCH_THREADS" \
    > "$BASE_DIR/llama.log" 2>&1 &
LLAMA_PID=$!
echo "[llama] PID=$LLAMA_PID"

# Wait for server to be ready
echo "[llama] Waiting for model to load..."
for i in $(seq 1 60); do
    if grep -q "server is listening" "$BASE_DIR/llama.log" 2>/dev/null; then
        echo "[llama] Ready! (${i}s)"
        break
    fi
    if ! kill -0 "$LLAMA_PID" 2>/dev/null; then
        echo "[llama] FAILED — check $BASE_DIR/llama.log"
        tail -10 "$BASE_DIR/llama.log" 2>/dev/null
        exit 1
    fi
    sleep 1
done

# ── Start mesh agent ───────────────────────────────────────
echo "[agent] Starting GIMO Mesh Agent..."

# Detect python
PYTHON=""
for p in python3 python; do
    if command -v "$p" > /dev/null 2>&1; then
        PYTHON="$p"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[agent] WARNING: Python not found — running inference-only mode"
    echo "[agent] Heartbeats will not be sent to GIMO server"
    echo "[llama] Running standalone on port $LLAMA_PORT"
    wait "$LLAMA_PID"
    exit 0
fi

cd "$BASE_DIR"
"$PYTHON" "$AGENT_SCRIPT" \
    --core-url "$GIMO_CORE_URL" \
    --token "$GIMO_TOKEN" \
    --device-id "$GIMO_DEVICE_ID" \
    --device-secret "$GIMO_DEVICE_SECRET" \
    --model-loaded "qwen2.5:3b" \
    --inference-endpoint "$INFERENCE_ENDPOINT" \
    --interval 30 &
AGENT_PID=$!
echo "[agent] PID=$AGENT_PID"
echo ""
echo "=== GIMO Mesh Node running ==="
echo "Inference: $INFERENCE_ENDPOINT/v1/chat/completions"
echo "Press Ctrl+C to stop"
echo ""

# Wait for either process to exit
wait -n "$LLAMA_PID" "$AGENT_PID" 2>/dev/null || true
echo "[node] A process exited — shutting down"
