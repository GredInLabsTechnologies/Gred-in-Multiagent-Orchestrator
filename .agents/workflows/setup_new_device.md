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

## 3. Bootstrap (installs everything automatically)

```bash
gimo bootstrap
```

This creates `.venv`, installs all Python/Node dependencies, generates tokens, and prepares `.env` files.

## 4. Copy Environment Variables (Secrets)
You must copy your environment files from your old machine to your new machine, as these contain secrets that are not in version control:
- `/apps/web/.env.local` (Firebase, Stripe, signing keys, etc.)

## 5. First Run & Auto-Configuration

> **`gimo.cmd` es el UNICO launcher de desarrollo oficial.** No uses ningun otro script.

```bash
gimo
```

This launches backend + frontend + web with interactive control and multiplexed logs. Type `q` to stop, `r` to restart backend, `s` for status.

## 6. Configure Provider (LLM)
Open the Orchestrator UI (usually http://localhost:5173).
Go to **Settings -> Providers**.

- If you have an NVIDIA GPU: Install SGLang via WSL2 and select it.
- If you have an AMD iGPU (e.g., ROG Ally X): Install **LM Studio**, enable the local API, and select it in GIMO.
- Alternatively, use a cloud provider like OpenAI or Groq.

## 7. IDE MCP Configuration
When you open cursor/windsurf, the MCP configuration file (`.mcp.json`) will be regenerated with the correct absolute paths for your new device. You don't need to copy the old one.
