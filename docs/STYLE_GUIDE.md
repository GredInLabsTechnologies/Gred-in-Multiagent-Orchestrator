# Guía de Estilo - Gred Repo Orchestrator

Este documento establece las convenciones de estilo y políticas de idioma para el proyecto Gred Repo Orchestrator.

## Tabla de Contenidos

- [Política de Idiomas](#política-de-idiomas)
- [Estilo de Código Python](#estilo-de-código-python)
- [Estilo de Código TypeScript](#estilo-de-código-typescript)
- [Documentación](#documentación)
- [Mensajes de Commit](#mensajes-de-commit)

---

## Política de Idiomas

### Resumen

El proyecto Gred Repo Orchestrator utiliza una política **bilingüe** para maximizar la accesibilidad:

| Elemento | Idioma | Razón |
|----------|--------|-------|
| **Código fuente** (variables, funciones, clases) | 🇬🇧 **Inglés** | Estándar internacional, mejor colaboración global |
| **Comentarios en código** | 🇬🇧 **Inglés** | Consistencia con código, facilita code review internacional |
| **Documentación técnica** | 🇬🇧 **Inglés** | DEVELOPMENT.md, ARCHITECTURE.md, API docs |
| **Documentación de usuario** | 🇪🇸 **Español** | README.md, guías de instalación, tutoriales |
| **Mensajes de commit** | 🇬🇧 **Inglés** | Estándar de la industria, historial comprensible globalmente |
| **Issues y PRs** | 🇬🇧/🇪🇸 **Bilingüe** | Según preferencia del contribuidor, traducir si es necesario |

### Justificación

#### ¿Por qué Inglés para Código?

1. **Colaboración internacional**: Facilita contribuciones de desarrolladores de cualquier país
2. **Estándar de la industria**: Frameworks, librerías y herramientas están en inglés
3. **Legibilidad**: Evita mezcla de idiomas en código (`obtener_user_data()` vs `get_user_data()`)
4. **Búsqueda y documentación**: Más fácil encontrar soluciones en Stack Overflow, etc.

#### ¿Por qué Español para Docs de Usuario?

1. **Audiencia objetivo**: Usuarios y administradores hispanohablantes
2. **Accesibilidad**: Menor barrera de entrada para usuarios no técnicos
3. **Claridad**: Conceptos complejos mejor explicados en idioma nativo

### Ejemplos

#### ✅ CORRECTO: Código en inglés, comentarios en inglés

```python
def calculate_hash(file_path: str) -> str:
    """
    Calculate SHA-256 hash of a file.

    Args:
        file_path: Absolute path to the file.

    Returns:
        SHA-256 hash in hexadecimal format.
    """
    # Read file in binary chunks to handle large files efficiently
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256.update(chunk)
    return sha256.hexdigest()
```

#### ❌ INCORRECTO: Mezcla de idiomas en código

```python
def calcular_hash(ruta_archivo: str) -> str:  # ❌ Función en español
    """
    Calculate SHA-256 hash of a file.  # ❌ Docstring en inglés
    """
    # Leer archivo en chunks binarios  # ❌ Comentario en español
    sha256_hash = hashlib.sha256()
    ...
```

---

## Estilo de Código Python

### Principios Generales

- **Formateo**: [Black](https://black.readthedocs.io/) (automático)
- **Linting**: [Ruff](https://docs.astral.sh/ruff/)
- **Imports**: [isort](https://pycqa.github.io/isort/)
- **Type hints**: Obligatorios en funciones públicas
- **Docstrings**: [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)

### Configuración

Ver [pyproject.toml](../pyproject.toml) para configuración completa:

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

### Naming Conventions

| Elemento | Convención | Ejemplo | Idioma |
|----------|------------|---------|--------|
| Variables | `snake_case` | `user_token`, `file_path` | 🇬🇧 Inglés |
| Funciones | `snake_case` | `get_repos()`, `validate_path()` | 🇬🇧 Inglés |
| Clases | `PascalCase` | `FileService`, `AuthValidator` | 🇬🇧 Inglés |
| Constantes | `UPPER_SNAKE_CASE` | `MAX_RETRIES`, `DEFAULT_PORT` | 🇬🇧 Inglés |
| Privadas | `_leading_underscore` | `_internal_helper()` | 🇬🇧 Inglés |
| Archivos | `snake_case.py` | `file_service.py` | 🇬🇧 Inglés |

### Docstrings

**Obligatorios para:**
- Todas las funciones públicas
- Todas las clases
- Módulos

**Formato:**

```python
def process_repository(repo_path: Path, options: Dict[str, Any]) -> RepoInfo:
    """
    Process a repository and extract metadata.

    This function validates the repository path, extracts Git information,
    and generates a structured metadata object.

    Args:
        repo_path: Absolute path to the repository root.
        options: Processing options including:
            - include_files: Whether to include file listing.
            - max_depth: Maximum directory depth to traverse.

    Returns:
        RepoInfo object containing metadata and file information.

    Raises:
        ValueError: If repo_path is not a valid directory.
        GitError: If repository is corrupted or unreadable.

    Example:
        >>> info = process_repository(Path("/repos/myproject"), {"include_files": True})
        >>> print(info.name)
        'myproject'
    """
    ...
```

### Comentarios

**Idioma:** 🇬🇧 **Inglés**

**Cuándo comentar:**

✅ **SÍ comentar:**
- Algoritmos complejos o no obvios
- Decisiones de diseño importantes
- Workarounds o hacks necesarios
- Referencias a issues o documentación externa
- TODOs con contexto

✅ **Ejemplos buenos:**

```python
# Use binary search for O(log n) lookup in sorted list
index = bisect.bisect_left(sorted_items, target)

# Workaround for Windows path limitations (MAX_PATH = 260)
# See: https://github.com/user/repo/issues/123
extended_path = f"\\\\?\\{path}"

# TODO(username): Refactor to use async I/O when Python 3.12 is adopted
# Issue: #456
data = sync_read_file(path)
```

❌ **NO comentar:**
- Código auto-explicativo
- Paráfrasis del código
- Comentarios obsoletos

❌ **Ejemplos malos:**

```python
# Increment counter
counter += 1  # ❌ Obvio

# Get user  # ❌ Paráfrasis
user = get_user()

# This function returns a list  # ❌ Type hint ya lo indica
def get_items() -> List[str]:
    ...
```

### Type Hints

**Obligatorios** en todas las funciones públicas:

```python
from typing import Optional, List, Dict, Union
from pathlib import Path

def search_files(
    root_dir: Path,
    pattern: str,
    max_results: Optional[int] = None
) -> List[Dict[str, Union[str, int]]]:
    ...
```

**Usar:**
- `Path` para rutas (no `str`)
- `Optional[T]` para valores que pueden ser `None`
- `Union[A, B]` para múltiples tipos
- `Dict[K, V]`, `List[T]`, `Set[T]` con tipos específicos

---

## Estilo de Código TypeScript

### Principios Generales

- **Linting**: ESLint v9 con flat config
- **Type safety**: TypeScript strict mode
- **Framework**: React 18 con functional components
- **Styling**: Tailwind CSS

### Naming Conventions

| Elemento | Convención | Ejemplo | Idioma |
|----------|------------|---------|--------|
| Variables | `camelCase` | `userToken`, `filePath` | 🇬🇧 Inglés |
| Funciones | `camelCase` | `getRepos()`, `validatePath()` | 🇬🇧 Inglés |
| Componentes | `PascalCase` | `FileList`, `AuthForm` | 🇬🇧 Inglés |
| Tipos/Interfaces | `PascalCase` | `RepoInfo`, `UserData` | 🇬🇧 Inglés |
| Constantes | `UPPER_SNAKE_CASE` | `MAX_RETRIES`, `API_URL` | 🇬🇧 Inglés |
| Archivos (componentes) | `PascalCase.tsx` | `FileList.tsx` | 🇬🇧 Inglés |
| Archivos (utilidades) | `camelCase.ts` | `apiClient.ts` | 🇬🇧 Inglés |

### React Components

**Formato preferido:**

```typescript
import React, { useState } from 'react';

interface RepoListProps {
  repos: Repository[];
  onSelect: (repo: Repository) => void;
}

/**
 * Display a list of repositories with selection capability.
 */
export const RepoList: React.FC<RepoListProps> = ({ repos, onSelect }) => {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const handleClick = (repo: Repository) => {
    setSelectedId(repo.id);
    onSelect(repo);
  };

  return (
    <div className="repo-list">
      {repos.map(repo => (
        <RepoCard
          key={repo.id}
          repo={repo}
          isSelected={repo.id === selectedId}
          onClick={() => handleClick(repo)}
        />
      ))}
    </div>
  );
};
```

### Comentarios

**Idioma:** 🇬🇧 **Inglés**

```typescript
// Debounce search input to avoid excessive API calls
const debouncedSearch = useMemo(
  () => debounce(performSearch, 300),
  [performSearch]
);

// TODO: Implement virtualization for large lists
// Issue: #789
const renderList = () => { ... };
```

---

## Documentación

### Documentación Técnica (Inglés)

Archivos en inglés:
- `docs/DEVELOPMENT.md` - Developer setup guide
- `docs/ARCHITECTURE.md` - Architecture documentation
- `docs/API.md` - API reference
- `docs/CONTRIBUTING.md` - Contribution guidelines
- Inline code documentation (docstrings, JSDoc)

**Formato:**

```markdown
# Development Guide

This document provides setup instructions for developers.

## Prerequisites

- Python 3.11+
- Node.js 18+

## Quick Start

...
```

### Documentación de Usuario (Español)

Archivos en español:
- `README.md` - Visión general del proyecto
- `docs/INSTALLATION.md` - Guía de instalación
- `docs/USER_GUIDE.md` - Guía de usuario
- `docs/FAQ.md` - Preguntas frecuentes

**Formato:**

```markdown
# Guía de Instalación

Este documento explica cómo instalar Gred Repo Orchestrator.

## Requisitos Previos

- Python 3.11 o superior
- Node.js 18 o superior

## Instalación Rápida

...
```

### Documentación Bilingüe (Opcional)

Para documentos importantes, considerar versiones bilingües:

```
docs/
├── INSTALLATION.md          (Español - principal)
├── INSTALLATION.en.md       (English - traducción)
├── USER_GUIDE.md            (Español - principal)
└── USER_GUIDE.en.md         (English - traducción)
```

---

## Mensajes de Commit

### Idioma

🇬🇧 **Inglés** (estándar de la industria)

### Formato

Usar [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Tipos

- `feat`: Nueva funcionalidad
- `fix`: Corrección de bug
- `docs`: Cambios en documentación
- `style`: Cambios de formateo (no afectan lógica)
- `refactor`: Refactorización de código
- `test`: Agregar o modificar tests
- `chore`: Tareas de mantenimiento
- `perf`: Mejora de rendimiento
- `ci`: Cambios en CI/CD
- `build`: Cambios en build system

### Ejemplos

**✅ Buenos mensajes:**

```
feat(auth): add JWT token validation

Implement JWT-based authentication with RS256 signature
verification. Tokens are validated on every API request.

Closes #123
```

```
fix(file-service): handle symlinks correctly

Previously, symlinks were followed which could expose files
outside allowed directories. Now symlinks are detected and
rejected with a 403 error.

Security fix for issue #456
```

```
docs(readme): update installation instructions

Add troubleshooting section for Windows users experiencing
path issues.
```

```
test(routes): add integration tests for panic mode

Cover scenarios:
- Panic activation during request
- Panic recovery flow
- Blocked endpoints during panic
```

**❌ Malos mensajes:**

```
fix bug  # ❌ Muy vago
```

```
Arreglar problema de autenticación  # ❌ Español
```

```
WIP  # ❌ No informativo
```

```
feat: add stuff and fix things and update docs  # ❌ Múltiples cambios sin estructura
```

### Scopes (Opcional)

Scopes comunes en este proyecto:

- `auth`: Autenticación y autorización
- `api`: Endpoints de API
- `ui`: Frontend/UI changes
- `security`: Seguridad
- `deps`: Dependencias
- `config`: Configuración
- `tests`: Testing infrastructure
- `ci`: CI/CD pipelines
- `docs`: Documentación

---

## Migración de Código Existente

### Prioridad

**Alta prioridad (migrar pronto):**
- Nombres de funciones y variables públicas
- Docstrings de funciones públicas
- Comentarios en código crítico de seguridad

**Baja prioridad (migrar eventualmente):**
- Comentarios en código interno
- Variables locales en funciones privadas

### Estrategia

1. **No refactorizar todo de golpe**: Migrar gradualmente en PRs con otros cambios
2. **Nuevos archivos**: Siempre en inglés
3. **Archivos modificados**: Convertir comentarios/docstrings tocados
4. **Tests**: Priorizar código de producción sobre tests

### Ejemplo de Migración

**Antes:**

```python
def calcular_hash(ruta: str) -> str:
    """Calcula el hash SHA-256 de un archivo."""
    # Abrir archivo en modo binario
    with open(ruta, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()
```

**Después:**

```python
def calculate_hash(file_path: str) -> str:
    """Calculate SHA-256 hash of a file."""
    # Open file in binary mode
    with open(file_path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()
```

---

## Herramientas

### Pre-commit Hooks

Los pre-commit hooks automáticamente verifican estilo:

```bash
# Instalar
pre-commit install

# Ejecutar manualmente
pre-commit run --all-files
```

### Linters y Formatters

```bash
# Python
black tools/ scripts/ tests/
ruff check tools/ scripts/ tests/
isort tools/ scripts/ tests/

# TypeScript
cd tools/orchestrator_ui
npm run lint
```

### Spell Checking (Opcional)

Para detectar typos en comentarios y docs:

```bash
# Instalar
pip install codespell

# Ejecutar
codespell tools/ scripts/ tests/ docs/
```

---

## Resumen Rápido

| Qué | Idioma | Ejemplo |
|-----|--------|---------|
| Código (variables, funciones) | 🇬🇧 Inglés | `calculate_hash()` |
| Comentarios en código | 🇬🇧 Inglés | `# Validate input` |
| Docstrings | 🇬🇧 Inglés | `"""Calculate hash..."""` |
| Commits | 🇬🇧 Inglés | `feat: add validation` |
| README | 🇪🇸 Español | `# GIL Orchestrator` |
| Docs técnicos | 🇬🇧 Inglés | `DEVELOPMENT.md` |
| Docs de usuario | 🇪🇸 Español | `INSTALLATION.md` |

---

**Última actualización:** 31 Enero 2026
**Mantenedor:** Equipo Gred Orchestrator
