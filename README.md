# GIL Orchestrator (Repo Management Tool) - [PRODUCTION READY]

Este repositorio contiene la herramienta de gestión y orquestación de repositorios (GIL Orchestrator), diseñada para exponer repositorios locales de forma segura a través de túneles Cloudflare y permitir la auditoría en tiempo real.

## Estado del Proyecto
- **Modo**: ESTRICTO SOLO LECTURA (Snapshot Read-Only).
- **Seguridad**: Certificada mediante Quality Gates (Integridad, Fuzzing, ASVS L3 Logic).
- **Limpieza**: Depurado de cualquier configuración externa (Rainmeter/Taskbar).

## Componentes
- **API Service**: `tools/repo_orchestrator/` (FastAPI).
- **Dashboard**: `tools/orchestrator_dashboard/` (React + Vite).
- **Service Deployment**: `scripts/` (Windows Service & Monitoring).

## Guía de Despliegue de Producción
1. **Configurar .env**: Asegúrate de que `ORCH_TOKEN` y `ORCH_REPO_ROOT` sean correctos.
2. **Instalar Dependencias**: `pip install -r requirements.txt` (si aplica) o usar el entorno virtual configurado.
3. **Activar Túnel**: `cloudflared service install <TOKEN>` para persistencia.
4. **Lanzar**: Ejecutar `scripts/start_orch.cmd`.

### Producción (Linux)

1. **Configurar .env**: Asegúrate de que `ORCH_TOKEN` y `ORCH_REPO_ROOT` sean correctos.
2. **Instalar Dependencias**: `pip install -r requirements.txt`.
3. **Lanzar**: Ejecutar `./scripts/start_orch.sh`.

**Systemd (opcional):**
```bash
sudo ./scripts/manage_service.sh install
sudo systemctl start gil-orchestrator
```

**Docker (opcional):**
```bash
docker compose up --build
```

## Auditoría y Control
Cada lectura de archivo se registra con un Hash SHA-256 en `logs/orchestrator_audit.log` y se sirve desde una copia temporal para proteger el código original.

## Desarrollo

### Configuración del Entorno de Desarrollo

#### Requisitos
- Python 3.11+
- Node.js 18+
- Git

#### Instalación de Dependencias

**Backend:**
```bash
# Producción
pip install -r requirements.txt

# Desarrollo (incluye herramientas de testing y calidad)
pip install -r requirements-dev.txt
```

**Frontend:**
```bash
cd tools/orchestrator_ui
npm install
```

#### Pre-commit Hooks

Este proyecto utiliza pre-commit hooks para mantener la calidad del código. Los hooks se ejecutan automáticamente antes de cada commit para:
- Formatear código Python con Black
- Verificar linting con Ruff
- Ordenar imports con isort
- Detectar problemas de seguridad con Bandit
- Validar formato de archivos (YAML, JSON, TOML)
- Eliminar trailing whitespace
- Asegurar end-of-file correctos

**Instalación:**
```bash
# Los hooks se instalan automáticamente al instalar requirements-dev.txt
# Si necesitas reinstalarlos manualmente:
pre-commit install
```

**Uso:**
```bash
# Ejecutar en todos los archivos
pre-commit run --all-files

# Ejecutar en archivos staged
pre-commit run

# Los hooks se ejecutan automáticamente en cada commit
git commit -m "mensaje"
```

**Configuración:** Ver [.pre-commit-config.yaml](.pre-commit-config.yaml) y [pyproject.toml](pyproject.toml)

### Ejecutar Tests

**Backend:**
```bash
# Tests unitarios
pytest tests/unit/ -v

# Tests con cobertura
pytest --cov=tools --cov=scripts --cov-report=term --cov-report=html
```

**Frontend:**
```bash
cd tools/orchestrator_ui
npm run test:coverage
```

### Linting y Formateo

**Frontend:**
```bash
cd tools/orchestrator_ui
npm run lint        # Ejecutar ESLint
npm run build       # Verificar build de producción
```

**Backend:**
```bash
# Formateo automático
black tools/ scripts/ tests/

# Linting
ruff check tools/ scripts/ tests/

# Ordenar imports
isort tools/ scripts/ tests/
```

### Ejecutar en Modo Desarrollo

**Backend:**
```bash
cd tools/repo_orchestrator
uvicorn main:app --reload --port 6834
```

**Frontend:**
```bash
cd tools/orchestrator_ui
npm run dev
```

## Herramientas de Calidad

- **ESLint v9**: Linting de TypeScript/JavaScript con flat config
- **Black**: Formateo de código Python (línea máxima: 100 caracteres)
- **Ruff**: Linting rápido de Python
- **isort**: Ordenamiento de imports Python
- **Bandit**: Análisis de seguridad estático
- **pytest + coverage**: Testing con cobertura
- **SonarCloud**: Análisis de calidad continuo en CI/CD
- **pip-audit**: Escaneo de vulnerabilidades en dependencias
