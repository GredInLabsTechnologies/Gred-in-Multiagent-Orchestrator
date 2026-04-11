#!/data/data/com.termux/files/usr/bin/bash
# Download Qwen2.5-3B-Instruct Q4_K_M for GIMO Mesh
set -e

MODEL_DIR=~/llama.cpp/models
MODEL_FILE="qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"

mkdir -p "$MODEL_DIR"
cd "$MODEL_DIR"

if [ -f "$MODEL_FILE" ]; then
    echo "Model already downloaded: $MODEL_FILE"
    ls -lh "$MODEL_FILE"
else
    echo "Downloading $MODEL_FILE (~2GB)..."
    echo "This will take a few minutes on WiFi."
    wget -c --progress=bar:force "$MODEL_URL" -O "$MODEL_FILE"
    echo ""
    echo "Download complete!"
    ls -lh "$MODEL_FILE"
fi

echo ""
echo "To start the inference server:"
echo "  cd ~/llama.cpp"
echo "  ./build/bin/llama-server -m models/$MODEL_FILE -c 2048 --host 0.0.0.0 --port 8080"
