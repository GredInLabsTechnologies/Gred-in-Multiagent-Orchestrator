#!/data/data/com.termux/files/usr/bin/bash
# GIMO Core bootstrap para Termux (Bionic-compatible).
#
# Diseño:
#   El bundle standalone (python-build-standalone) es glibc-linked y NO corre
#   en Android Bionic. En lugar de ese bundle, Termux provee Python nativo
#   compilado contra Bionic via `pkg install python`. Este script:
#     1. Instala Python + deps vía pkg (pre-built Termux wheels para
#        cryptography/psutil/pillow/numpy — evita compiles de ~15 min)
#     2. Extrae un tarball del repo GIMO Core (producido con
#        scripts/push_repo_to_termux.cmd desde el host)
#     3. pip install -r requirements.txt — incluye rove-toolkit desde
#        vendor/rove/ (wheelhouse forge para peer-to-peer upgrades). Con
#        --prefer-binary tira de wheels aarch64; resto compila si no hay.
#     4. Verifica que rove es importable (auto-check del distribution layer)
#     5. Arranca `python -m tools.gimo_server.main --role server`
#
# Uso (en Termux, tras adb push a /sdcard):
#   termux-setup-storage          # una vez, concede acceso al almacenamiento
#   cp /storage/emulated/0/Download/gimo-repo.tar.gz ~
#   cp /storage/emulated/0/Download/termux_core_bootstrap.sh ~
#   bash ~/termux_core_bootstrap.sh
#
# Variables de entorno respetadas:
#   ORCH_TOKEN                     (obligatorio en server mode)
#   GIMO_MESH_HOST_DEVICE_ID       (default: termux-$(hostname))
#   GIMO_CORE_PORT                 (default: 9325)
#   GIMO_REPO_TARBALL              (default: ~/gimo-repo.tar.gz)
#   GIMO_REPO_DIR                  (default: ~/gimo-core)
#   SKIP_PKG_INSTALL=1             (skip pkg install si ya está hecho)
set -euo pipefail

# Colores para signals legibles
C="\033[1;36m"; W="\033[1;33m"; R="\033[1;31m"; E="\033[0m"
step()  { printf "${C}[gimo]${E} %s\n" "$*"; }
warn()  { printf "${W}[gimo]${E} %s\n" "$*"; }
fail()  { printf "${R}[gimo]${E} %s\n" "$*" >&2; exit 1; }

# ─── Verificar entorno Termux ────────────────────────────────────────────
if [ ! -d "/data/data/com.termux" ]; then
    fail "Este script debe ejecutarse dentro de Termux. /data/data/com.termux no existe."
fi

PORT="${GIMO_CORE_PORT:-9325}"
DEVICE_ID="${GIMO_MESH_HOST_DEVICE_ID:-termux-$(hostname 2>/dev/null || echo s10)}"
REPO_DIR="${GIMO_REPO_DIR:-$HOME/gimo-core}"

# Auto-locate tarball: first env var override, then /sdcard/Download (adb push
# target), then ~/. User no debería tener que cp manualmente.
CANDIDATES=(
    "${GIMO_REPO_TARBALL:-}"
    "/storage/emulated/0/Download/gimo-repo.tar.gz"
    "$HOME/gimo-repo.tar.gz"
)
REPO_TARBALL=""
for c in "${CANDIDATES[@]}"; do
    if [ -n "$c" ] && [ -f "$c" ]; then
        REPO_TARBALL="$c"
        break
    fi
done

# También auto-locate el token (opcional)
TOKEN_CANDIDATES=(
    "${ORCH_TOKEN_FILE:-}"
    "/storage/emulated/0/Download/.orch_token"
    "$HOME/gimo-core/.orch_token"
)
TOKEN_FILE=""
for c in "${TOKEN_CANDIDATES[@]}"; do
    if [ -n "$c" ] && [ -f "$c" ]; then
        TOKEN_FILE="$c"
        break
    fi
done

# ─── Step 1: pkg install Python + deps ───────────────────────────────────
if [ -z "${SKIP_PKG_INSTALL:-}" ]; then
    step "Updating Termux package index..."
    pkg update -y >/dev/null 2>&1 || warn "pkg update devolvió warnings (ignorable)"

    step "Installing python + git + pre-built wheels (~100 MB)..."
    # Pre-built Termux wheels evitan compilar binarios pesados:
    #   python-cryptography → skip Rust 15+ min build
    #   python-psutil       → setup.py rechaza explícitamente Android
    #   python-pillow/numpy → skip C extensions
    # rust se mantiene como fallback si pydantic-core no encuentra wheel.
    pkg install -y python python-pip git clang make libffi openssl rust \
        python-cryptography python-psutil python-pillow python-numpy \
        binutils cmake pkg-config >/dev/null 2>&1 || \
        fail "pkg install falló - revisa conectividad y espacio en disco"

    step "Termux Python ready: $(python --version 2>&1)"
else
    step "Skipping pkg install (SKIP_PKG_INSTALL set)"
fi

# ─── Step 2: Extract repo tarball ────────────────────────────────────────
if [ -z "$REPO_TARBALL" ] || [ ! -f "$REPO_TARBALL" ]; then
    fail "No se encuentra el tarball. Busqué en:
    - \$GIMO_REPO_TARBALL (env var)
    - /storage/emulated/0/Download/gimo-repo.tar.gz
    - ~/gimo-repo.tar.gz

    Para prepararlo desde el host Windows:
        scripts\\push_repo_to_termux.cmd

    Asegúrate de haber corrido 'termux-setup-storage' al menos una vez
    para que Termux pueda leer /storage/emulated/0/Download/."
fi

step "Using tarball: $REPO_TARBALL"

if [ -d "$REPO_DIR" ]; then
    warn "$REPO_DIR ya existe - respetando contenido. Borra manualmente para fresh extract."
else
    step "Extracting repo to $REPO_DIR..."
    mkdir -p "$REPO_DIR"
    tar -xzf "$REPO_TARBALL" -C "$REPO_DIR"
fi

# ─── Step 3: pip install deps ────────────────────────────────────────────
cd "$REPO_DIR"
if [ ! -f "requirements.txt" ]; then
    fail "requirements.txt no encontrado en $REPO_DIR - tarball inválido?"
fi

MARKER="$HOME/.gimo-deps-installed"
if [ ! -f "$MARKER" ] || [ "requirements.txt" -nt "$MARKER" ]; then
    step "Installing Python deps (--prefer-binary, cryptography ya provisto via pkg)..."
    pip install --upgrade pip wheel setuptools >/dev/null 2>&1
    # --prefer-binary fuerza wheels primero. cryptography/pillow/numpy ya están
    # via pkg (system site-packages) y satisfacen los requirements.
    # requirements.txt incluye ./vendor/rove/rove_toolkit-1.0.0-py3-none-any.whl
    # — pip lo resuelve relativo a $REPO_DIR donde ya estamos via `cd`.
    #
    # Env vars requeridos cuando algún sdist cae a compile (p.ej. pydantic-core
    # via maturin — no hay wheel pre-built para la combinación Python+Android
    # de Termux). Los valores vienen del patch registry rove-patches
    # (vendor/rove-patches/patches/maturin/android-api-level.env). Sin ellos,
    # maturin abortaría con metadata-generation-failed.
    export ANDROID_API_LEVEL=24
    export ANDROID_PLATFORM=android-24
    pip install --prefer-binary -r requirements.txt || fail "pip install falló"
    touch "$MARKER"
else
    step "Deps cache hit (marker present). Delete $MARKER para reinstalar."
fi

# ─── Step 3b: Verify rove wheelhouse forge ────────────────────────────────
# Rove provee peer-to-peer distribution + verificación Ed25519 para runtime
# upgrades. Si falla el import, el Core arranca pero `runtime_upgrader`
# y endpoints `/ops/mesh/runtime-*` no funcionan. Fail-fast aquí.
if ! python -c "import rove.manifest, rove.signing.ed25519" 2>/dev/null; then
    fail "rove-toolkit no importa tras pip install — revisa vendor/rove/ \
y que el wheel esté incluido en el tarball del repo."
fi
step "rove-toolkit $(python -c 'import rove; print(getattr(rove, \"__version__\", \"1.0.0\"))') ready"

# ─── Step 4: Resolve ORCH_TOKEN ──────────────────────────────────────────
TOKEN="${ORCH_TOKEN:-}"
if [ -z "$TOKEN" ]; then
    if [ -n "$TOKEN_FILE" ] && [ -f "$TOKEN_FILE" ]; then
        TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
        step "ORCH_TOKEN loaded from $TOKEN_FILE"
    elif [ -f "$REPO_DIR/.orch_token" ]; then
        TOKEN=$(cat "$REPO_DIR/.orch_token" | tr -d '[:space:]')
        step "ORCH_TOKEN loaded from $REPO_DIR/.orch_token"
    else
        warn "ORCH_TOKEN no esta set y no hay .orch_token - server rechazara rutas auth."
    fi
fi

# ─── Step 5: Launch Core ─────────────────────────────────────────────────
export ORCH_TOKEN="$TOKEN"
export GIMO_MESH_HOST_ENABLED=true
export GIMO_MESH_HOST_DEVICE_ID="$DEVICE_ID"
export GIMO_MESH_HOST_DEVICE_MODE=server
export GIMO_MESH_HOST_DEVICE_CLASS=smartphone
export ORCH_MDNS_ENABLED=true
export PYTHONPATH="$REPO_DIR:${PYTHONPATH:-}"

step "Launching GIMO Core:"
echo "    python  = $(which python)"
echo "    role    = server"
echo "    port    = $PORT"
echo "    device  = $DEVICE_ID"
echo "    repo    = $REPO_DIR"
echo ""

exec python -m tools.gimo_server.main --role server \
    --mesh-host-id "$DEVICE_ID" \
    --mesh-host-class smartphone \
    --port "$PORT"
