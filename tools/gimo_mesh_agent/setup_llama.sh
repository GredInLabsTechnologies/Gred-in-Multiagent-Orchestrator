#!/data/data/com.termux/files/usr/bin/bash
# GIMO Mesh — llama.cpp setup for Android/Termux
# No root required. CPU-only (ARM NEON).

set -e

echo "========================================="
echo " GIMO Mesh — llama.cpp Installer"
echo "========================================="
echo ""

# 1. Install build dependencies
echo "[1/4] Installing build dependencies..."
pkg update -y
pkg install -y git cmake make clang wget

# 2. Clone llama.cpp
echo ""
echo "[2/4] Cloning llama.cpp..."
cd ~
if [ -d "llama.cpp" ]; then
    echo "  llama.cpp already exists, pulling latest..."
    cd llama.cpp && git pull && cd ..
else
    git clone --depth 1 https://github.com/ggerganov/llama.cpp
fi

# 3. Build
echo ""
echo "[3/4] Building llama.cpp (this takes ~5 minutes)..."
cd ~/llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j4

# Verify build
if [ -f "build/bin/llama-server" ]; then
    echo "  llama-server built successfully!"
elif [ -f "build/bin/server" ]; then
    echo "  server built successfully!"
else
    echo "  ERROR: build failed!"
    ls build/bin/ 2>/dev/null
    exit 1
fi

echo ""
echo "[4/4] Creating models directory..."
mkdir -p ~/llama.cpp/models

echo ""
echo "========================================="
echo " BUILD COMPLETE"
echo ""
echo " Next: download a model with:"
echo "   cd ~/llama.cpp/models"
echo "   wget <model-url>"
echo "========================================="
