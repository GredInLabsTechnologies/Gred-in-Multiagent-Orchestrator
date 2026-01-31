# Reporte de Auditoría de Seguridad - Fase 1

**Fecha:** 31 Enero 2026
**Herramienta:** pip-audit v2.10.0
**Repositorio:** Gred-Repo-Orchestrator

---

## Resumen Ejecutivo

- **Vulnerabilidades encontradas:** 18 CVEs
- **Paquetes afectados:** 9
- **Severidad:** ALTA - Requiere acción inmediata

---

## Vulnerabilidades Detalladas

### 🔴 CRÍTICO (7 CVEs)

#### pypdf 5.9.0 → 6.6.2
**Impacto:** Librería para procesamiento PDF con múltiples vulnerabilidades
- CVE-2025-55197 - Fix: 6.0.0
- CVE-2025-62707 - Fix: 6.1.3
- CVE-2025-62708 - Fix: 6.1.3
- CVE-2025-66019 - Fix: 6.4.0
- CVE-2026-22690 - Fix: 6.6.0
- CVE-2026-22691 - Fix: 6.6.0
- CVE-2026-24688 - Fix: 6.6.2

**Acción:** Actualizar a pypdf>=6.6.2

---

### 🟡 ALTA (3 CVEs)

#### urllib3 2.5.0 → 2.6.3
**Impacto:** Librería HTTP core, usada por requests
- CVE-2025-66418 - Fix: 2.6.0
- CVE-2025-66471 - Fix: 2.6.0
- CVE-2026-21441 - Fix: 2.6.3

**Acción:** Actualizar a urllib3>=2.6.3

---

### 🟡 MEDIA (8 CVEs)

#### filelock 3.20.0 → 3.20.3
- CVE-2025-68146 - Fix: 3.20.1
- CVE-2026-22701 - Fix: 3.20.3

**Acción:** Actualizar a filelock>=3.20.3

#### starlette 0.47.2 → 0.49.1
**Impacto:** Framework ASGI core para FastAPI
- CVE-2025-62727 - Fix: 0.49.1

**Acción:** Actualizar a starlette>=0.49.1

#### python-multipart 0.0.21 → 0.0.22
**Impacto:** Parser para multipart/form-data
- CVE-2026-24486 - Fix: 0.0.22

**Acción:** Actualizar a python-multipart>=0.0.22

#### pip 25.0.1 → 25.3
- CVE-2025-8869 - Fix: 25.3

**Acción:** Actualizar pip: `python -m pip install --upgrade pip`

#### pyasn1 0.6.1 → 0.6.2
- CVE-2026-23490 - Fix: 0.6.2

**Acción:** Actualizar a pyasn1>=0.6.2

---

### ⚠️ SIN CORRECCIÓN DISPONIBLE

#### protobuf 5.29.5
- CVE-2026-0994 - **Sin fix version especificada**

**Acción:** Monitorear actualizaciones, considerar alternativas si crítico

#### xhtml2pdf 0.2.15
- CVE-2024-25885 - **Sin fix version especificada**

**Acción:** Monitorear actualizaciones, evaluar necesidad de esta dependencia

---

## Paquetes No Auditables

Los siguientes paquetes no pudieron ser auditados porque usan versiones CUDA customizadas no disponibles en PyPI:

- `torch (2.7.1+cu118)`
- `torchaudio (2.7.1+cu118)`
- `torchvision (0.22.1+cu118)`

**Nota:** Esto refuerza la sospecha de que estos paquetes ML/AI podrían no ser necesarios para el proyecto. Ver Tarea 1.2 para auditoría de uso.

---

## Plan de Remediación

### Acción Inmediata (Hoy)

1. **Actualizar paquetes críticos:**
```bash
pip install --upgrade pypdf>=6.6.2
pip install --upgrade urllib3>=2.6.3
pip install --upgrade filelock>=3.20.3
pip install --upgrade starlette>=0.49.1
pip install --upgrade python-multipart>=0.0.22
pip install --upgrade pyasn1>=0.6.2
python -m pip install --upgrade pip
```

2. **Ejecutar tests después de actualizaciones:**
```bash
pytest tests/unit/ -v
pytest --cov=tools --cov=scripts --cov-report=term
```

3. **Verificar que la aplicación funciona correctamente:**
```bash
python -m tools.repo_orchestrator.main
```

### Corto Plazo (1-2 días)

1. **Investigar vulnerabilidades sin corrección:**
   - protobuf CVE-2026-0994
   - xhtml2pdf CVE-2024-25885

2. **Evaluar impacto en producción:**
   - Revisar si xhtml2pdf es realmente necesario
   - Considerar alternativas para protobuf si la vulnerabilidad es crítica

### Automatización (1 semana)

1. **Agregar pip-audit a CI/CD** (ver Tarea 2.2)
2. **Configurar alertas automáticas de seguridad** en GitHub
3. **Establecer policy de actualización de seguridad semanal**

---

## Actualización de requirements.txt

Después de aplicar las correcciones, actualizar [requirements.txt](requirements.txt) con las versiones corregidas:

```
pypdf>=6.6.2
urllib3>=2.6.3
filelock>=3.20.3
starlette>=0.49.1
python-multipart>=0.0.22
pyasn1>=0.6.2
```

---

## Próximos Pasos

1. ✅ Tarea 1.1 completada - Escaneo realizado
2. ⏳ Aplicar actualizaciones de seguridad
3. ⏳ Tarea 1.2 - Auditoría de dependencias no usadas
4. ⏳ Tarea 1.3 - Crear requirements-dev.txt
5. ⏳ Tarea 1.4 - Remover dependencias innecesarias

---

**Conclusión:** El proyecto tiene vulnerabilidades de seguridad que deben ser atendidas inmediatamente, especialmente en pypdf (7 CVEs) y urllib3 (3 CVEs). Sin embargo, todas tienen correcciones disponibles y pueden ser resueltas con actualizaciones simples.
