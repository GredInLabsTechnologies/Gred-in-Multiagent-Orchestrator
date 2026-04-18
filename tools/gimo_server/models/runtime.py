"""
GIMO Core Runtime Manifest — Thin shim over rove.manifest.WheelhouseManifest
============================================================================
El schema canónico del bundle vive ahora en :class:`rove.manifest.WheelhouseManifest`
(``rove-toolkit`` v1.0.0 vendorizado en ``vendor/rove/``). Este módulo sólo
re-exporta los símbolos con los nombres que GIMO usaba antes de la migración
para no forzar renames de imports en el resto del codebase.

Aliases:

- :class:`RuntimeManifest`    → :class:`rove.manifest.WheelhouseManifest`
- :class:`RuntimeTarget`      → :class:`rove.manifest.Target`
- :class:`RuntimeCompression` → :class:`rove.manifest.Compression`

Diferencias visibles vs el schema pre-rove:

* ``project_name`` es REQUIRED (str, regex ``^[a-z0-9][a-z0-9._-]*$``).
  Los productores GIMO emiten ``project_name="gimo-core"``.
* ``repo_root_rel_path`` → ``project_root_rel_path`` (campo renombrado).
* ``wheels_rel_path`` y ``patches_applied`` son campos nuevos (opcional).
* ``signing_payload()`` es 4-tupla ``<sha>|<target>|<version>|<project_name>``
  — breaking change vs rove 0.1.x / GIMO pre-vendor. Any non-Python verifier
  (Kotlin, Rust) debe actualizarse en lockstep.

Los field-validators de rove son un superset de los de GIMO: además de
rechazar paths absolutos (Windows drive / POSIX ``/``), rechazan travesías
``..`` y prefijos UNC ``\\\\``. La migración añade seguridad sin perder nada.

Migración a rove 1.0.0 — 2026-04-18.
"""
from __future__ import annotations

from rove.manifest import (
    Compression as RuntimeCompression,
    Target as RuntimeTarget,
    WheelhouseManifest as RuntimeManifest,
)

__all__ = ["RuntimeCompression", "RuntimeTarget", "RuntimeManifest"]
