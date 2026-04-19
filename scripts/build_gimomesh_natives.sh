#!/usr/bin/env bash
# build_gimomesh_natives.sh — cross-compile llama-server for android-arm64 +
# android-x86_64 and place both under apps/android/gimomesh/app/src/main/jniLibs/
# as strip-ready libllama-server.so. Re-runnable; idempotent per ABI.
#
# G10 fix: automates the manual sequence we ran during G2 + G3 validation.
# Previously the artifact was built by hand, stripped by hand, and copied
# by hand. That's a release hazard — this script captures the canonical
# invocation + catches regressions in llama.cpp upstream.
#
# Requirements:
#   - Android NDK (≥27 recommended)
#   - cmake + ninja in PATH (Android Studio ships them under
#     <sdk>/cmake/3.22.1/bin/)
#   - git + curl
#   - An "llama.cpp" checkout (cloned into $WORKDIR/llama.cpp if missing)
#
# Environment variables:
#   NDK            Path to Android NDK (required if ANDROID_NDK_HOME unset)
#   WORKDIR        Scratch dir for build (default: /tmp/llama-build)
#   ABIS           Space-separated ABIs to build (default: "arm64-v8a x86_64")
#   ANDROID_PLATFORM (default: android-28 — minimum for posix_spawn used by
#                    llama.cpp's vendored subprocess.h)

set -euo pipefail

NDK="${NDK:-${ANDROID_NDK_HOME:-}}"
if [[ -z "$NDK" || ! -d "$NDK" ]]; then
  echo "ERROR: set NDK or ANDROID_NDK_HOME to an Android NDK directory" >&2
  exit 2
fi

WORKDIR="${WORKDIR:-/tmp/llama-build}"
ABIS="${ABIS:-arm64-v8a x86_64}"
ANDROID_PLATFORM="${ANDROID_PLATFORM:-android-28}"
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
JNI_ROOT="$REPO_ROOT/apps/android/gimomesh/app/src/main/jniLibs"

mkdir -p "$WORKDIR"
cd "$WORKDIR"

# ---- clone llama.cpp once ----
if [[ ! -d llama.cpp ]]; then
  echo "[fetch] cloning llama.cpp..."
  git clone --depth 1 https://github.com/ggml-org/llama.cpp
fi

# Detect host toolchain dir. NDK ships prebuilt binaries per host.
HOST_TC=""
for candidate in windows-x86_64 linux-x86_64 darwin-x86_64 darwin-arm64; do
  if [[ -d "$NDK/toolchains/llvm/prebuilt/$candidate" ]]; then
    HOST_TC="$candidate"
    break
  fi
done
if [[ -z "$HOST_TC" ]]; then
  echo "ERROR: could not locate NDK host toolchain under $NDK/toolchains/llvm/prebuilt/" >&2
  exit 3
fi
STRIP="$NDK/toolchains/llvm/prebuilt/$HOST_TC/bin/llvm-strip"
[[ "$HOST_TC" == "windows-x86_64" ]] && STRIP="${STRIP}.exe"

# ---- build per ABI ----
for ABI in $ABIS; do
  BUILD_DIR="$WORKDIR/llama.cpp/build-android-$ABI"
  DEST_DIR="$JNI_ROOT/$ABI"
  mkdir -p "$DEST_DIR"
  echo ""
  echo "======================================================="
  echo " [build] ABI=$ABI  platform=$ANDROID_PLATFORM"
  echo "======================================================="

  rm -rf "$BUILD_DIR"
  mkdir -p "$BUILD_DIR"
  cd "$BUILD_DIR"

  cmake ../llama.cpp -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI="$ABI" \
    -DANDROID_PLATFORM="$ANDROID_PLATFORM" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_CURL=OFF \
    -DGGML_BACKEND_DL=OFF \
    -DGGML_OPENMP=OFF \
    -DBUILD_SHARED_LIBS=OFF \
    >/dev/null

  cmake --build . --config Release -j "$(nproc 2>/dev/null || echo 4)" \
    --target llama-server >/dev/null

  # The compiled binary lives in bin/llama-server (Windows: bin/llama-server,
  # the extension is not .exe because it's an Android ELF).
  if [[ ! -f bin/llama-server ]]; then
    echo "ERROR: expected bin/llama-server in $BUILD_DIR" >&2
    exit 4
  fi

  cp bin/llama-server "$DEST_DIR/libllama-server.so"
  "$STRIP" --strip-all "$DEST_DIR/libllama-server.so"

  size=$(stat -c %s "$DEST_DIR/libllama-server.so" 2>/dev/null \
         || stat -f %z "$DEST_DIR/libllama-server.so")
  echo "  [ok] $DEST_DIR/libllama-server.so ($((size/1024/1024)) MB stripped)"

  cd "$WORKDIR"
done

echo ""
echo "======================================================="
echo " done. Built for: $ABIS"
echo "======================================================="
echo ""
echo "Final jniLibs contents:"
find "$JNI_ROOT" -name "libllama-server.so" -exec ls -la {} +
echo ""
echo "Next: ./gradlew assembleDebug  (from apps/android/gimomesh/)"
