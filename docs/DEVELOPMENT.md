# Guía de Desarrollo - Gred Repo Orchestrator

Este documento proporciona una guía completa para desarrolladores que desean contribuir al proyecto Gred Repo Orchestrator.

## Tabla de Contenidos

- [Prerrequisitos](#prerrequisitos)
- [Setup Inicial](#setup-inicial)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Ejecutar Localmente](#ejecutar-localmente)
- [Ejecutar Tests](#ejecutar-tests)
- [Convenciones de Código](#convenciones-de-código)
- [Workflow de Desarrollo](#workflow-de-desarrollo)
- [Troubleshooting](#troubleshooting)

---

## Prerrequisitos

Antes de comenzar, asegúrate de tener instalado:

### Software Requerido

- **Python 3.11+**: Lenguaje principal del backend
  - Verificar: `python --version` o `python3 --version`
  - Descargar: [python.org](https://www.python.org/downloads/)

- **Node.js 18+**: Entorno de ejecución para el frontend
  - Verificar: `node --version`
  - Descargar: [nodejs.org](https://nodejs.org/)

- **Git**: Sistema de control de versiones
  - Verificar: `git --version`
  - Descargar: [git-scm.com](https://git-scm.com/)

### Software Opcional pero Recomendado

- **Cloudflare Tunnel** (cloudflared): Para exposición segura de túneles
  - Descargar: [developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/)

- **IDE recomendado**: Visual Studio Code
  - Con extensiones: Python, ESLint, Prettier, GitLens

---

## Setup Inicial

### 1. Clonar el Repositorio

```bash
git clone https://github.com/tu-usuario/Gred-Repo-Orchestrator.git
cd Gred-Repo-Orchestrator
```

### 2. Configurar Backend (Python)

#### 2.1. Crear Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

#### 2.2. Instalar Dependencias

**Para desarrollo (recomendado):**
```bash
pip install -r requirements-dev.txt
```

Esto instala:
- Dependencias de producción (`requirements.txt`)
- Herramientas de testing (pytest, coverage)
- Herramientas de calidad (black, ruff, isort)
- Herramientas de seguridad (pip-audit, bandit)
- Pre-commit hooks

**Solo para producción:**
```bash
pip install -r requirements.txt
```

#### 2.3. Configurar Variables de Entorno

Copia el archivo de ejemplo y ajusta según tu entorno:

```bash
cp .env.example .env
```

Edita `.env` con tus valores:
```env
ORCH_TOKEN=tu-token-secreto-aqui
ORCH_REPO_ROOT=C:/Users/tu-usuario/Documents/GitHub
ORCH_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
ORCH_RATE_LIMIT_WINDOW_SECONDS=60
ORCH_SUBPROCESS_TIMEOUT=10
```

**Nota:** Si `ORCH_TOKEN` está vacío, se autogenera uno al iniciar.

#### 2.4. Instalar Pre-commit Hooks

Los pre-commit hooks garantizan la calidad del código antes de cada commit:

```bash
pre-commit install
```

Ejecutar en todos los archivos (primera vez):
```bash
pre-commit run --all-files
```

### 3. Configurar Frontend (React + TypeScript)

```bash
cd tools/orchestrator_ui
npm install
cd ../..
```

### 4. Verificar Instalación

Ejecutar tests para verificar que todo está configurado correctamente:

```bash
# Backend tests
pytest tests/unit/ -v

# Frontend tests
cd tools/orchestrator_ui
npm run test:coverage
cd ../..
```

---

## Estructura del Proyecto

```
Gred-Repo-Orchestrator/
│
├── .github/                      # GitHub Actions workflows
│   └── workflows/
│       └── sonar.yml            # CI/CD con SonarCloud
│
├── docs/                        # Documentación
│   ├── DEVELOPMENT.md           # Esta guía
│   ├── ARCHITECTURE.md          # Diagramas y arquitectura
│   ├── SONAR.md                 # Guía de SonarCloud
│   └── RECOVERY_GUIDE.md        # Guía de recuperación
│
├── scripts/                     # Scripts de despliegue y utilidades
│   ├── start_orch.cmd           # Entry point principal (Windows)
│   ├── launch_orchestrator.ps1  # Lanzador PowerShell
│   ├── manage_service.ps1       # Gestión de servicio Windows
│   ├── installer_gui.py         # Instalador GUI
│   ├── analyze_dependencies.py  # Auditoría de dependencias
│   └── ...                      # Otros scripts de utilidad
│
├── tests/                       # Suite de tests
│   ├── unit/                    # Tests unitarios
│   │   ├── test_routes.py
│   │   ├── test_security_*.py
│   │   └── ...
│   ├── llm/                     # Tests de seguridad LLM
│   ├── metrics/                 # Reportes de métricas
│   └── conftest.py              # Configuración compartida de pytest
│
├── tools/
│   ├── repo_orchestrator/       # Backend FastAPI
│   │   ├── main.py              # Aplicación FastAPI principal
│   │   ├── routes.py            # Endpoints de API
│   │   ├── config.py            # Configuración
│   │   ├── models.py            # Modelos Pydantic
│   │   ├── security/            # Módulos de seguridad
│   │   │   ├── auth.py          # Autenticación
│   │   │   ├── audit.py         # Auditoría SHA-256
│   │   │   ├── validation.py    # Validación de paths
│   │   │   └── rate_limit.py    # Rate limiting
│   │   └── services/            # Capa de servicios
│   │       ├── file_service.py  # Operaciones de archivos
│   │       ├── git_service.py   # Operaciones Git
│   │       ├── repo_service.py  # Gestión de repos
│   │       ├── snapshot_service.py  # Snapshots read-only
│   │       └── system_service.py    # Operaciones del sistema
│   │
│   └── orchestrator_ui/         # Frontend React + TypeScript
│       ├── src/
│       │   ├── App.tsx          # Componente raíz
│       │   ├── main.tsx         # Entry point
│       │   ├── components/      # Componentes reutilizables
│       │   ├── hooks/           # Custom React hooks
│       │   │   ├── useRepoService.ts
│       │   │   ├── useSecurityService.ts
│       │   │   └── useSystemService.ts
│       │   ├── islands/         # Componentes de islas
│       │   └── types.ts         # Definiciones TypeScript
│       ├── package.json
│       ├── vite.config.ts
│       └── tsconfig.json
│
├── .env.example                 # Template de variables de entorno
├── .gitignore                   # Archivos ignorados por Git
├── .pre-commit-config.yaml      # Configuración de pre-commit hooks
├── pyproject.toml               # Configuración de herramientas Python
├── requirements.txt             # Dependencias de producción
├── requirements-dev.txt         # Dependencias de desarrollo
├── pytest.ini                   # Configuración de pytest
├── sonar-project.properties     # Configuración de SonarCloud
└── README.md                    # Documentación principal
```

### Componentes Clave

#### Backend (FastAPI)

- **[main.py](../tools/repo_orchestrator/main.py)**: Aplicación FastAPI principal (208 líneas)
- **[routes.py](../tools/repo_orchestrator/routes.py)**: Definición de endpoints de API (258 líneas)
- **[config.py](../tools/repo_orchestrator/config.py)**: Configuración centralizada (108 líneas)
- **security/**: Módulos de seguridad (autenticación, auditoría, validación)
- **services/**: Capa de lógica de negocio

#### Frontend (React + TypeScript)

- **Arquitectura de Islas**: Componentes modulares e independientes
- **Custom Hooks**: Separación de lógica de negocio
- **Tailwind CSS**: Estilos utility-first

---

## Ejecutar Localmente

### Modo Desarrollo

#### Backend

```bash
cd tools/repo_orchestrator
uvicorn main:app --reload --port 6834
```

El backend estará disponible en:
- API: [http://localhost:6834](http://localhost:6834)
- Documentación interactiva: [http://localhost:6834/docs](http://localhost:6834/docs)
- OpenAPI Schema: [http://localhost:6834/openapi.json](http://localhost:6834/openapi.json)

#### Frontend

En otra terminal:

```bash
cd tools/orchestrator_ui
npm run dev
```

El frontend estará disponible en:
- UI: [http://localhost:5173](http://localhost:5173)

### Modo Producción (Windows)

```bash
scripts\start_orch.cmd
```

Este script:
1. Activa el virtual environment
2. Valida la configuración
3. Inicia el backend FastAPI
4. Sirve el frontend compilado

### Modo Producción (Linux)

```bash
./scripts/start_orch.sh
```

Este script:
1. Detecta el directorio base
2. Autogenera ORCH_TOKEN si falta
3. Verifica procesos previos en el puerto 9325
4. Inicia FastAPI con uvicorn

#### Systemd (opcional)

```bash
sudo ./scripts/manage_service.sh install
sudo systemctl start gil-orchestrator
```

#### Docker (opcional)

```bash
docker compose up --build
```

---

## Ejecutar Tests

### Tests Backend (Python)

#### Tests Unitarios

```bash
# Todos los tests unitarios
pytest tests/unit/ -v

# Tests específicos
pytest tests/unit/test_routes.py -v
pytest tests/unit/test_security_core.py -v

# Con output detallado
pytest tests/unit/ -v --tb=short
```

#### Tests con Cobertura

```bash
# Generar reporte de cobertura
pytest --cov=tools --cov=scripts --cov-report=term --cov-report=html

# Ver reporte HTML
# Abrir: htmlcov/index.html en navegador
```

#### Tests de Seguridad

```bash
# Tests de fuzzing
pytest tests/test_fuzzing.py -v

# Tests de autenticación
pytest tests/test_auth_validation.py -v

# Tests de seguridad LLM
pytest tests/test_llm_security_leakage.py -v

# Chaos engineering
pytest tests/test_load_chaos_resilience.py -v
```

#### Escaneo de Vulnerabilidades

```bash
# Auditoría de dependencias
pip-audit

# Análisis de seguridad estático
bandit -r tools/ scripts/ -ll
```

### Tests Frontend (TypeScript)

```bash
cd tools/orchestrator_ui

# Ejecutar tests con cobertura
npm run test:coverage

# Modo watch (desarrollo)
npm test

# Ver reporte de cobertura
# Abrir: coverage/lcov-report/index.html
```

### Linting y Formateo

#### Backend

```bash
# Formateo automático con Black
black tools/ scripts/ tests/

# Linting con Ruff
ruff check tools/ scripts/ tests/

# Ordenar imports
isort tools/ scripts/ tests/

# Ejecutar todo (pre-commit)
pre-commit run --all-files
```

#### Frontend

```bash
cd tools/orchestrator_ui

# Linting con ESLint
npm run lint

# Build de producción
npm run build

# Preview del build
npm run preview
```

---

## Convenciones de Código

### Python

#### Estilo

- **Formateo**: Black (línea máxima: 100 caracteres)
- **Imports**: isort (organización automática)
- **Linting**: Ruff (reglas extendidas)

Configuración en [pyproject.toml](../pyproject.toml):

```toml
[tool.black]
line-length = 100
target-version = ['py311']

[tool.isort]
profile = "black"
line_length = 100

[tool.ruff]
line-length = 100
target-version = "py311"
```

#### Naming Conventions

- **Variables/Funciones**: `snake_case`
- **Clases**: `PascalCase`
- **Constantes**: `UPPER_SNAKE_CASE`
- **Archivos**: `snake_case.py`

#### Docstrings

Usar docstrings de Google style:

```python
def calculate_hash(file_path: str) -> str:
    """
    Calcula el hash SHA-256 de un archivo.

    Args:
        file_path: Ruta absoluta al archivo.

    Returns:
        Hash SHA-256 en formato hexadecimal.

    Raises:
        FileNotFoundError: Si el archivo no existe.
    """
    ...
```

#### Type Hints

Siempre usar type hints:

```python
from typing import Optional, List, Dict

def get_repos(limit: Optional[int] = None) -> List[Dict[str, str]]:
    ...
```

### TypeScript/JavaScript

#### Estilo

- **Linting**: ESLint v9 con flat config
- **Type Safety**: TypeScript strict mode habilitado

Configuración en [tsconfig.json](../tools/orchestrator_ui/tsconfig.json):

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true
  }
}
```

#### Naming Conventions

- **Variables/Funciones**: `camelCase`
- **Componentes/Clases**: `PascalCase`
- **Constantes**: `UPPER_SNAKE_CASE`
- **Archivos de componentes**: `PascalCase.tsx`
- **Archivos de utilidades**: `camelCase.ts`

#### React Components

Preferir functional components con hooks:

```tsx
interface Props {
  title: string;
  onAction: () => void;
}

export const MyComponent: React.FC<Props> = ({ title, onAction }) => {
  const [state, setState] = useState<string>('');

  return (
    <div>
      <h1>{title}</h1>
      <button onClick={onAction}>Action</button>
    </div>
  );
};
```

---

## Workflow de Desarrollo

### 1. Crear Feature Branch

```bash
git checkout -b feature/mi-nueva-funcionalidad
```

### 2. Desarrollar

- Escribe código siguiendo las convenciones
- Ejecuta tests frecuentemente
- Commitea cambios incrementales

### 3. Commitear Cambios

Los pre-commit hooks se ejecutarán automáticamente:

```bash
git add .
git commit -m "feat: Agregar nueva funcionalidad X"
```

#### Formato de Mensajes de Commit

Usar [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` Nueva funcionalidad
- `fix:` Corrección de bug
- `docs:` Cambios en documentación
- `style:` Cambios de formateo (no afectan lógica)
- `refactor:` Refactorización de código
- `test:` Agregar o modificar tests
- `chore:` Tareas de mantenimiento

Ejemplos:
```
feat: Add repository snapshot service
fix: Correct path validation in file_service
docs: Update DEVELOPMENT.md with testing guide
test: Add unit tests for auth module
```

### 4. Ejecutar Suite Completa de Tests

Antes de push:

```bash
# Backend
pytest tests/unit/ -v
pytest --cov=tools --cov=scripts

# Frontend
cd tools/orchestrator_ui
npm run test:coverage
npm run build
cd ../..

# Linting
pre-commit run --all-files
```

### 5. Push y Pull Request

```bash
git push origin feature/mi-nueva-funcionalidad
```

Crear Pull Request en GitHub con:
- Título descriptivo
- Descripción de cambios
- Link a issues relacionados
- Checklist de testing

### 6. Code Review

- CI/CD ejecuta automáticamente (GitHub Actions)
- SonarCloud analiza calidad y seguridad
- Revisión de código por maintainers

---

## Troubleshooting

### Problemas Comunes

#### 1. Tests fallando con `NameError: name 'patch' is not defined`

**Solución:** Agregar import al inicio del archivo de test:

```python
from unittest.mock import patch, MagicMock, call
```

#### 2. Backend no inicia - Puerto 6834 en uso

**Solución:** Cambiar puerto temporalmente:

```bash
uvicorn main:app --reload --port 6835
```

O liberar el puerto:

**Windows:**
```bash
netstat -ano | findstr :6834
taskkill /PID <PID> /F
```

**Linux/macOS:**
```bash
lsof -ti:6834 | xargs kill -9
```

#### 7. Permisos al instalar systemd

Si el script `manage_service.sh` falla en Linux:

```bash
sudo ./scripts/manage_service.sh install
sudo systemctl daemon-reload
sudo systemctl start gil-orchestrator
```

#### 3. Frontend no conecta con backend

**Verificar:**
1. Backend está ejecutándose en puerto 6834
2. CORS configurado en `.env`:
   ```
   ORCH_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
   ```
3. Frontend usa la URL correcta en `src/hooks/`

#### 4. Pre-commit hooks fallan

**Solución:** Ejecutar formateo manual:

```bash
black tools/ scripts/ tests/
isort tools/ scripts/ tests/
ruff check --fix tools/ scripts/ tests/
```

Luego commitear de nuevo.

#### 5. Dependencias faltantes

**Solución:** Reinstalar dependencias:

```bash
# Backend
pip install -r requirements-dev.txt

# Frontend
cd tools/orchestrator_ui
npm install
```

#### 6. Tests de integridad fallan

Si `test_critical_file_integrity` falla:

1. Regenerar manifest:
   ```bash
   python tests/verify_snapshots.py --update
   ```

2. Revisar cambios en archivos críticos:
   ```bash
   git diff tools/repo_orchestrator/
   ```

---

## Recursos Adicionales

### Documentación del Proyecto

- [README.md](../README.md) - Visión general
- [ARCHITECTURE.md](./ARCHITECTURE.md) - Arquitectura detallada
- [SONAR.md](./SONAR.md) - Configuración de SonarCloud
- [RECOVERY_GUIDE.md](./RECOVERY_GUIDE.md) - Guía de recuperación

### Documentación Externa

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [React Documentation](https://react.dev/)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)
- [Pytest Documentation](https://docs.pytest.org/)
- [Vite Documentation](https://vitejs.dev/)

### Herramientas

- [Black Playground](https://black.vercel.app/) - Probar formateo Black
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [ESLint Rules](https://eslint.org/docs/latest/rules/)

---

## Soporte

Si encuentras problemas o tienes preguntas:

1. Revisar esta guía de desarrollo
2. Consultar [issues existentes en GitHub](https://github.com/tu-usuario/Gred-Repo-Orchestrator/issues)
3. Crear un nuevo issue con:
   - Descripción del problema
   - Pasos para reproducir
   - Logs relevantes
   - Entorno (OS, versiones de Python/Node)

---

**Última actualización:** 31 Enero 2026
**Mantenedor:** Equipo Gred Orchestrator
