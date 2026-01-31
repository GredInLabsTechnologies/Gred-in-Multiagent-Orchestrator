FROM python:3.11-slim AS backend

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/repo_orchestrator ./tools/repo_orchestrator
COPY tools/repo_orchestrator/security_db.json ./tools/repo_orchestrator/security_db.json
COPY tools/repo_orchestrator/repo_registry.json ./tools/repo_orchestrator/repo_registry.json
COPY tools/repo_orchestrator/allowed_paths.json ./tools/repo_orchestrator/allowed_paths.json
COPY logs ./logs
COPY .env.example ./.env.example

ENV PYTHONPATH=/app
EXPOSE 9325

CMD ["uvicorn", "tools.repo_orchestrator.main:app", "--host", "0.0.0.0", "--port", "9325"]
