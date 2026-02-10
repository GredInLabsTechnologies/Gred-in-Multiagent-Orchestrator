# CI / Quality Gates

This repo uses **local quality gates** and a **GitHub Actions CI pipeline** to prevent regressions.

## Local gates (recommended before any PR)

Backend:

```cmd
pip install -r requirements.txt -r requirements-dev.txt
pre-commit run --all-files
python scripts\\ci\\check_no_artifacts.py --tracked
python scripts\\ci\\quality_gates.py
python -m pytest -m "not integration" -v
```

UI:

```cmd
cd tools\orchestrator_ui
npm ci
npm run lint
npm run test:coverage
npm run build
```

## LLM / adversarial suites

Some suites require an **OpenAI-compatible LLM server**.

Environment variables:

- `LM_STUDIO_REQUIRED=1` → fail tests if the LLM is unreachable
- `LM_STUDIO_HOST=http://localhost:1234/v1` → OpenAI-compatible base URL
- `LM_STUDIO_MODEL=...` → model identifier expected by your server

### Option A: LM Studio (desktop)

Run LM Studio locally (OpenAI API), then:

```cmd
set LM_STUDIO_REQUIRED=1
set LM_STUDIO_HOST=http://localhost:1234/v1
set LM_STUDIO_MODEL=qwen/qwen3-8b
python -m pytest tests/adversarial -v --tb=short
python -m pytest tests/test_adaptive_attack_vectors.py -v --tb=short
python -m pytest tests/test_qwen_payload_guided.py -v --tb=short
```

### Option B: Ollama (headless, CI-friendly)

If you have Docker:

```cmd
docker run -d --name ollama -p 11434:11434 ollama/ollama
docker exec ollama ollama pull qwen2.5:0.5b
set LM_STUDIO_REQUIRED=1
set LM_STUDIO_HOST=http://localhost:11434/v1
set LM_STUDIO_MODEL=qwen2.5:0.5b
python -m pytest tests/adversarial -v --tb=short
```

## What CI enforces

See:

- `.github/workflows/ci.yml`

The pipeline runs:

1) Python gates (pre-commit + repo policy + quality gates)
2) Python tests (non-integration)
3) UI lint/test/build
4) LLM/adversarial suites (required)
