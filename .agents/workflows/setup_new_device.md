---
description: How to setup GIMO on a new device
---

# Setup GIMO on a new device

Follow these steps to quickly set up GIMO (Gred In Multiagent Orchestrator) on a new device (e.g., ROG Ally X, new PC).

## 1. Prerequisites
Ensure you have the following installed on the new device:
- **Git**
- **Python 3.11+**
- **Node.js 18+**

## 2. Clone the Repository
Clone the monorepo to your new machine:
```bash
git clone https://github.com/GredInLabsTechnologies/Gred-in-Multiagent-Orchestrator.git
cd Gred-in-Multiagent-Orchestrator
```

## 3. Install Dependencies
Run the following commands to install dependencies for the backend, frontend UI, and GIMO Web:

```bash
# 3.1 Backend (Python)
pip install -r requirements.txt

# 3.2 Orchestrator UI (React)
cd tools/orchestrator_ui
npm ci
cd ../..

# 3.3 GIMO Web (Next.js)
cd apps/web
npm ci
cd ../..
```

## 4. Copy Environment Variables (Secrets)
You must copy your environment files from your old machine to your new machine, as these contain secrets that are not in version control:
- `/apps/web/.env.local` (Firebase, Stripe, signing keys, etc.)

## 5. First Run & Auto-Configuration
Start the orchestrator backend. This will automatically generate the required tokens (`.orch_token`, `.orch_operator_token`, `.orch_actions_token`) and scan your computer for repositories to build `repo_registry.json`.

```bash
GIMO_DEV_LAUNCHER.cmd
```
*(Alternatively, run `python -m tools.gimo_server.main` directly if not on Windows)*

## 6. Configure Provider (LLM)
Open the Orchestrator UI (usually http://localhost:5173).
Go to **Settings -> Providers**.

- If you have an NVIDIA GPU: Install SGLang via WSL2 and select it.
- If you have an AMD iGPU (e.g., ROG Ally X): Install **LM Studio**, enable the local API, and select it in GIMO.
- Alternatively, use a cloud provider like OpenAI or Groq.

## 7. IDE MCP Configuration
When you open cursor/windsurf, the MCP configuration file (`.mcp.json`) will be regenerated with the correct absolute paths for your new device. You don't need to copy the old one.
