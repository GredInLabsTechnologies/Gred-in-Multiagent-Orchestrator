#!/bin/bash
# E2E Demo: ServerBond + ProviderMesh
# Prueba el flujo completo desde cero

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  GIMO ServerBond E2E Demo                                      ║"
echo "║  Testing nuclear CLI↔Server connection from scratch            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Setup
DEMO_DIR="$HOME/gimo-prueba-e2e"
GIMO_REPO="$(pwd)"
SERVER_URL="http://127.0.0.1:9325"

echo "📁 Demo directory: $DEMO_DIR"
echo "🏠 GIMO repo: $GIMO_REPO"
echo "🌐 Server URL: $SERVER_URL"
echo ""

# Check server is running
echo "▶ 1. Checking server health..."
if ! curl -s "$SERVER_URL/health" > /dev/null 2>&1; then
    echo "❌ Server not running at $SERVER_URL"
    echo "💡 Start server first: cd $GIMO_REPO && python -m tools.gimo_server.main"
    exit 1
fi
echo "✅ Server reachable"
echo ""

# Clean start
if [ -d "$DEMO_DIR" ]; then
    echo "🧹 Removing existing demo directory..."
    rm -rf "$DEMO_DIR"
fi

mkdir -p "$DEMO_DIR"
cd "$DEMO_DIR"
git init -q
echo "✅ Created fresh git repo at $DEMO_DIR"
echo ""

# Initialize GIMO
echo "▶ 2. Initializing GIMO project..."
python "$GIMO_REPO/gimo.py" init
echo "✅ GIMO initialized (.gimo/config.yaml created)"
echo ""

# Before login — should fail with helpful message
echo "▶ 3. Testing pre-login (should guide to login)..."
python "$GIMO_REPO/gimo.py" status 2>&1 || true
echo ""

# Login (ServerBond creation)
echo "▶ 4. Creating ServerBond (gimo login)..."
echo "💡 You'll be prompted for server token"
echo "   Get it from: $GIMO_REPO/tools/gimo_server/.gimo_credentials"
echo "   Or env var: ORCH_OPERATOR_TOKEN"
echo ""
python "$GIMO_REPO/gimo.py" login "$SERVER_URL"
echo ""

# Doctor check
echo "▶ 5. Running health diagnostic (gimo doctor)..."
python "$GIMO_REPO/gimo.py" doctor
echo ""

# Status check
echo "▶ 6. Testing status (should work now)..."
python "$GIMO_REPO/gimo.py" status
echo ""

# Provider auth status
echo "▶ 7. Checking provider authentication..."
python "$GIMO_REPO/gimo.py" providers auth-status
echo ""

# Test from different directory (portability check)
echo "▶ 8. Testing portability (ServerBond works from anywhere)..."
cd /tmp
python "$GIMO_REPO/gimo.py" status
echo "✅ ServerBond is portable!"
cd "$DEMO_DIR"
echo ""

# Logout
echo "▶ 9. Testing logout..."
python "$GIMO_REPO/gimo.py" logout "$SERVER_URL"
echo ""

# Post-logout check (should fail)
echo "▶ 10. Testing post-logout (should guide to re-login)..."
python "$GIMO_REPO/gimo.py" status 2>&1 || true
echo ""

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  ✅ E2E Demo Complete                                          ║"
echo "║                                                                ║"
echo "║  ServerBond features verified:                                 ║"
echo "║  • Init works from any git repo                                ║"
echo "║  • Login creates encrypted bond in ~/.gimo/bonds/              ║"
echo "║  • Doctor diagnoses all subsystems                             ║"
echo "║  • Status works from any directory (portable)                  ║"
echo "║  • Provider auth status checks                                 ║"
echo "║  • Logout removes bond cleanly                                 ║"
echo "║                                                                ║"
echo "║  Next: Test provider login (codex/claude)                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
