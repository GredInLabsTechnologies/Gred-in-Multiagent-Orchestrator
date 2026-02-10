FROM python:3.11-slim AS backend

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/gimo_server ./tools/gimo_server
COPY tools/gimo_server/security_db.json ./tools/gimo_server/security_db.json
COPY tools/gimo_server/repo_registry.json ./tools/gimo_server/repo_registry.json
COPY tools/gimo_server/allowed_paths.json ./tools/gimo_server/allowed_paths.json
COPY logs ./logs
COPY .env.example ./.env.example

ENV PYTHONPATH=/app
EXPOSE 9325

CMD ["uvicorn", "tools.gimo_server.main:app", "--host", "0.0.0.0", "--port", "9325"]
