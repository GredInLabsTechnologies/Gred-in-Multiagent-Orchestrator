# Evidence pack

This folder contains **reproducible artifacts** proving that the documentation matches the code and that the project passed the agreed verification steps.

Recommended contents (examples):

- `quality_gates_YYYYMMDD_HHMM.txt`
- `pytest_full_YYYYMMDD_HHMM.txt`
- `bandit_YYYYMMDD_HHMM.txt`
- `pip_audit_YYYYMMDD_HHMM.txt`
- `docker_build_YYYYMMDD_HHMM.txt`
- `ui_build_YYYYMMDD_HHMM.txt`
- `ui_lint_YYYYMMDD_HHMM.txt`
- `ui_test_coverage_YYYYMMDD_HHMM.txt`

Rule: any claim marked as **VALIDATED** in `docs/DOCS_REGISTRY.md` should reference at least one artifact in this folder.

## Recommended commands (copy/paste)

### Backend (Python)

- Full test suite:

  ```cmd
  python -m pytest -q > docs\evidence\pytest_full_YYYYMMDD_HHMM.txt 2>&1
  ```

  Note: scripts were reorganized under `scripts/{dev,ops,ci,tools}`.
  Use:

  ```cmd
  python scripts\\ci\\quality_gates.py > docs\\evidence\\quality_gates_YYYYMMDD_HHMM.txt 2>&1
  ```

- Quality gates:

  ```cmd
  python scripts\ci\quality_gates.py > docs\evidence\quality_gates_YYYYMMDD_HHMM.txt 2>&1
  ```

- Dependency audit (requires pip-audit installed):

  ```cmd
  pip-audit -r requirements.txt -r requirements-dev.txt > docs\evidence\pip_audit_YYYYMMDD_HHMM.txt 2>&1
  ```

- Static security scan (requires bandit installed):

  ```cmd
  bandit -r tools -r scripts -q > docs\evidence\bandit_YYYYMMDD_HHMM.txt 2>&1
  ```

### Frontend (tools/orchestrator_ui)

```cmd
npm --prefix tools\orchestrator_ui run lint > docs\evidence\ui_lint_YYYYMMDD_HHMM.txt 2>&1
npm --prefix tools\orchestrator_ui run build > docs\evidence\ui_build_YYYYMMDD_HHMM.txt 2>&1
npm --prefix tools\orchestrator_ui run test:coverage > docs\evidence\ui_test_coverage_YYYYMMDD_HHMM.txt 2>&1
```

Dependency audit:

```cmd
npm --prefix tools\orchestrator_ui audit > docs\evidence\ui_npm_audit_YYYYMMDD_HHMM.txt 2>&1
```

### Docker

```cmd
docker build -t gred-orchestrator:local . > docs\evidence\docker_build_YYYYMMDD_HHMM.txt 2>&1
docker compose up --build > docs\evidence\docker_compose_up_YYYYMMDD_HHMM.txt 2>&1
```
