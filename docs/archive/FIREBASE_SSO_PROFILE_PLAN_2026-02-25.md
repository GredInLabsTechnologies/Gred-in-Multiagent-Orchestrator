# Firebase SSO + Mi Perfil — Plan de Implementación

> **Status:** ACTIVE
> **Fecha:** 2026-02-25
> **Supersedes:** `docs/UI_IMPROVEMENT_PLAN_2026-02-23.md` (Fases 1-2 completadas, Fase 3 parcialmente integrada aquí)
> **Scope:** GIMO WEB (`gimo-web/`) + Orquestador backend (`tools/gimo_server/`) + Frontend (`tools/orchestrator_ui/`)
> **Ejecutores:** Agentes delegados (Cline, Gemini, etc.) — Revisión final por Claude

---

## Problema

El sistema de tokens del orquestador (ORCH_TOKEN) es frágil: se pierde entre reinicios, el usuario tiene que copiar/pegar manualmente, y bloquea el uso. **GIMO WEB** ya tiene Firebase Auth (Google Sign-In) + Stripe + licencias. El objetivo es que el orquestador use el mismo sistema de auth de GIMO WEB (SSO) para que el usuario inicie sesión con Google y nunca más tenga que tocar tokens.

## Decisiones de Diseño

| Decisión | Elección | Alternativa descartada |
|----------|----------|----------------------|
| Auth primario | Firebase/Google SSO directo | Magic link email, GitHub OAuth |
| Billing | Enlace externo a GIMO WEB | Stripe embebido en orquestador |
| Token local | Queda como fallback colapsable (dev) | Eliminarlo completamente |
| Sesión Firebase | Cookie httpOnly 30 días | JWT en localStorage |
| Datos de perfil | Proxy vía backend al GIMO WEB API | Firebase Admin SDK directo en orquestador |

## Logos

Copiar a `tools/orchestrator_ui/public/`:

| Origen | Destino | Uso |
|--------|---------|-----|
| `C:\Users\shilo\Pictures\Logo moderno de GRED IN LABS letras negras.png` | `public/logo-dark.png` | Fondos claros |
| `C:\Users\shilo\Pictures\ChatGPT Image 12 feb 2026, 06_40_38 letras blancas.png` | `public/logo-light.png` | UI principal (fondo oscuro) |
| `C:\Users\shilo\Pictures\ChatGPT Image 12 feb 2026, 06_43_31solo logo.png` | `public/logo-icon.png` | Favicon, avatar placeholder |

---

## FASE 1: Endpoint de verificación en GIMO WEB

**Repo**: `C:\Users\shilo\Documents\Github\GIMO WEB\gimo-web\`
**Complejidad**: Baja | **Dependencias**: Ninguna

### Objetivo
Crear un endpoint que el orquestador pueda llamar para verificar un Firebase ID Token y obtener datos del usuario + licencia.

### Checklist

- [ ] **Crear** `src/app/api/orchestrator/verify/route.ts`
  - `POST` protegido con header `X-Internal-Key` (comparar con env `GIMO_INTERNAL_KEY`)
  - Recibe: `{ idToken: string }`
  - Verifica idToken con `adminAuth.verifyIdToken(idToken)` (reusar `src/lib/firebase-admin.ts`)
  - Busca usuario en Firestore (`users` collection)
  - Busca licencia activa en Firestore (`licenses` collection, `userId == uid`, `status == "active"`)
  - Busca suscripción (`subscriptions` collection)
  - Response schema:
    ```json
    {
      "uid": "string",
      "email": "string",
      "displayName": "string",
      "role": "user|admin",
      "license": {
        "plan": "standard|admin|none",
        "status": "active|expired|suspended|none",
        "isLifetime": false,
        "keyPreview": "abcd1234",
        "installationsUsed": 1,
        "installationsMax": 2,
        "expiresAt": "ISO string|null"
      },
      "subscription": {
        "status": "active|canceled|past_due|none",
        "currentPeriodEnd": "ISO string|null",
        "cancelAtPeriodEnd": false
      }
    }
    ```
  - Si no tiene licencia: `license.plan = "none"`, `license.status = "none"`

- [ ] **Añadir** env var `GIMO_INTERNAL_KEY` a `.env.local` y `.env.example`

### Archivos referencia
- `src/lib/firebase-admin.ts` — adminAuth, adminDb
- `src/lib/auth-middleware.ts` — Patrón de verificación
- `src/app/api/license/route.ts` — Cómo buscar licencias por userId

### Verificación
```bash
curl -X POST http://localhost:3000/api/orchestrator/verify \
  -H "X-Internal-Key: test" \
  -H "Content-Type: application/json" \
  -d '{"idToken": "..."}'
```

---

## FASE 2: Backend del orquestador — Firebase login

**Repo**: `C:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator\`
**Complejidad**: Media | **Dependencias**: Fase 1

### Objetivo
Nuevo endpoint que recibe un Firebase ID Token, lo verifica contra GIMO WEB, y crea una sesión cookie de 30 días.

### Checklist

- [ ] **Modificar** `tools/gimo_server/config.py`
  - Añadir a `Settings` (dataclass frozen):
    - `gimo_web_url: str` (env: `GIMO_WEB_URL`, default: `https://gimo-web.vercel.app`)
    - `gimo_internal_key: str` (env: `GIMO_INTERNAL_KEY`, default: `""`)
  - Exportar como constantes: `GIMO_WEB_URL`, `GIMO_INTERNAL_KEY`

- [ ] **Modificar** `tools/gimo_server/security/auth.py`
  - Extender `_Session` con campos opcionales:
    - `uid: str = ""`
    - `email: str = ""`
    - `display_name: str = ""`
    - `plan: str = ""`
    - `firebase_user: bool = False`
  - Añadir `FIREBASE_SESSION_TTL = 86400 * 30` (30 días)
  - En `SessionStore.create()`: aceptar kwargs para los nuevos campos
  - En `validate()`: usar TTL correcto según `session.firebase_user`
  - Nuevo método `get_session_info(cookie_value) -> dict` para endpoint de profile

- [ ] **Modificar** `tools/gimo_server/routers/auth_router.py`
  - **Nuevo endpoint `POST /auth/firebase-login`**:
    - Recibe `{ idToken: string }`
    - Llama a `{GIMO_WEB_URL}/api/orchestrator/verify` con header `X-Internal-Key`
    - Si válido: crea sesión con uid, email, plan, `firebase_user=True`, TTL 30 días
    - Set cookie `gimo_session`
    - Retorna `{ role, email, displayName, plan }`
  - **Nuevo endpoint `GET /auth/profile`**:
    - Requiere sesión activa (`verify_token`)
    - Si `firebase_user`: llama a GIMO WEB para datos frescos de licencia (o usa cache)
    - Retorna profile completo: usuario + licencia + suscripción + sesión info
  - **Modificar `GET /auth/check`**:
    - Añadir `email`, `displayName`, `plan` a la respuesta si sesión Firebase

### Archivos referencia
- `tools/gimo_server/security/auth.py` — `SessionStore`, `_Session`, `verify_token`
- `tools/gimo_server/routers/auth_router.py` — Login/logout existentes
- `tools/gimo_server/config.py` — Patrón de `Settings`

### Verificación
```bash
# Backend arrancado
curl -X POST http://127.0.0.1:9325/auth/firebase-login \
  -H "Content-Type: application/json" \
  -d '{"idToken": "VALID_FIREBASE_TOKEN"}' \
  -c cookies.txt

curl http://127.0.0.1:9325/auth/check -b cookies.txt
# Debe retornar: authenticated + email + plan
```

---

## FASE 3: Frontend — Firebase SDK + Login con Google

**Repo**: `C:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator\tools\orchestrator_ui\`
**Complejidad**: Media | **Dependencias**: Fase 2

### Objetivo
Integrar Firebase Auth en el frontend. El login principal es "Iniciar sesión con Google". El token local queda como fallback colapsable.

### Checklist

- [ ] **Instalar** dependencia: `npm install firebase`

- [ ] **Copiar logos** a `public/` (ver tabla de Logos arriba)

- [ ] **Crear** `src/lib/firebase.ts`
  - Misma estructura que GIMO WEB: `initializeApp` + `getAuth`
  - Env vars: `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, etc.
  - Exportar `auth` y `googleProvider` (`new GoogleAuthProvider()`)

- [ ] **Crear** `.env.example` con vars Firebase (valores placeholder)

- [ ] **Reescribir** `src/components/LoginModal.tsx`
  - Logo GRED IN LABS (letras blancas, `logo-light.png`) centrado arriba
  - Botón principal: "Iniciar sesión con Google" (estilo macOS, azul `#0a84ff`)
    - `signInWithPopup(auth, googleProvider)`
    - `user.getIdToken()` → `POST /auth/firebase-login`
    - Si OK → cierra modal
  - Sección colapsable: "Acceso por token local (desarrollo)" — input de token como antes
  - Errores con toast (`useToast()`)

- [ ] **Modificar** `src/App.tsx`
  - Al montar: `GET /auth/check`
    - Autenticado → cargar app
    - No → mostrar LoginModal
  - Guardar datos del usuario (email, displayName, plan) en state/context
  - Pasar info a MenuBar para avatar

### Archivos referencia
- `src/components/LoginModal.tsx` — Login actual (reescribir)
- `src/App.tsx` — Flujo de auth actual
- `GIMO WEB/gimo-web/src/lib/firebase.ts` — Patrón Firebase init
- `GIMO WEB/gimo-web/src/components/google-auth-button.tsx` — Patrón Google Sign-In

### Verificación
- [ ] Abrir `http://127.0.0.1:5173` → ver logo + botón Google
- [ ] Click → popup Google → login → dashboard cargado
- [ ] Cerrar pestaña → reabrir → auto-login (cookie 30 días)
- [ ] Token local → sigue funcionando como fallback

---

## FASE 4: Frontend — Panel "Mi Perfil"

**Repo**: `C:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator\tools\orchestrator_ui\`
**Complejidad**: Media | **Dependencias**: Fase 3

### Objetivo
Sección "Mi Perfil" accesible desde MenuBar con toda la info de cuenta.

### Checklist

- [ ] **Crear** `src/hooks/useProfile.ts`
  - `GET /auth/profile` con `credentials: 'include'`
  - Auto-refetch cada 5 minutos
  - Retorna `{ profile, loading, error, refetch }`

- [ ] **Crear** `src/components/ProfilePanel.tsx`
  - Diseño tipo tarjetas (mismo estilo que `SettingsPanel.tsx`):

  **a) Cabecera**
  - Foto de Google (o `logo-icon.png` como fallback) + nombre + email
  - Badge: plan (Standard = azul `#0a84ff`, Lifetime = dorado `#ff9f0a`, Free = gris `#86868b`)

  **b) Suscripción**
  - Estado con badge (activa = verde `#32d74b`, expirada = rojo `#ff453a`, free = gris)
  - Si activa: próximo cobro (fecha) + "$3/mes"
  - Si `cancelAtPeriodEnd`: "Se cancela el [fecha]"
  - Botón: "Gestionar suscripción" → `window.open('https://gimo-web.vercel.app/account', '_blank')`

  **c) Licencia**
  - Key preview: `••••••••abcd1234` + botón copiar
  - Instalaciones: barra visual progress (X / Y)
  - Estado: active/expired/suspended con badge
  - Botón: "Gestionar licencia" → abre GIMO WEB

  **d) Sesión Local** (colapsable)
  - Rol actual
  - Token ORCH_TOKEN enmascarado + copiar
  - Tiempo restante de sesión
  - Botón "Cerrar sesión" → `POST /auth/logout` + `signOut(auth)`

  **e) Setup Rápido** (colapsable)
  - Código CLI: `gimo auth --key <TU_LICENSE_KEY>`
  - Enlace a docs/GIMO WEB

- [ ] **Modificar** `src/components/MenuBar.tsx`
  - Esquina superior derecha: avatar circular (foto Google o `logo-icon.png`)
  - Click → abre ProfilePanel (panel lateral o modal)
  - Nombre truncado al lado del avatar

- [ ] **Modificar** `src/App.tsx`
  - Añadir ProfilePanel al sistema de vistas
  - Pasar datos de usuario al MenuBar

- [ ] **Modificar** `src/types.ts`
  - Añadir tipos: `UserProfile`, `LicenseInfo`, `SubscriptionInfo`

### Archivos referencia
- `src/components/SettingsPanel.tsx` — Patrón de diseño (tarjetas, toggles, grid)
- `src/components/Toast.tsx` — `useToast()` para feedback
- `src/types.ts` — Tipos existentes

### Verificación
- [ ] Login con Google → click en avatar → ver perfil completo
- [ ] Plan, licencia, suscripción visibles
- [ ] "Gestionar suscripción" abre GIMO WEB en nueva pestaña
- [ ] "Cerrar sesión" → logout → vuelve a LoginModal

---

## FASE 5: Revisión y Testing

**Ejecutor**: Claude
**Dependencias**: Fases 1-4 completadas

### Checklist

- [ ] Revisar código de las 4 fases (correctness, security, patterns)
- [ ] TypeScript check: `npx tsc --noEmit` → 0 errores
- [ ] Backend tests: `pytest tests/` → sin regresiones
- [ ] Verificar que MCP bridge sigue funcionando (Bearer token no afectado)
- [ ] Testing manual completo del flujo SSO
- [ ] Commit final con todos los cambios

---

## Notas para Agentes

- **Auth pattern frontend**: Siempre `credentials: 'include'`, NUNCA `Authorization: Bearer`. El backend usa cookies httpOnly con HMAC-signed sessions (`tools/gimo_server/security/auth.py`)
- **API_BASE**: Importar desde `../types` → `export const API_BASE = ...`
- **Design system**: Dark theme macOS-like. Colores: bg `#0a0a0a`/`#141414`, accent `#0a84ff`, success `#32d74b`, warning `#ff9f0a`, danger `#ff453a`, text `#f5f5f7`, muted `#86868b`, border `#2c2c2e`
- **Toast system**: `import { useToast } from './Toast'` → `const { addToast } = useToast()`
- **Config dataclass**: `tools/gimo_server/config.py` usa frozen dataclass con prefix `ORCH_` para env vars
- **No crear archivos innecesarios**. Preferir editar los existentes
- **ReactFlow**: v11 (import from `reactflow`, no `@xyflow/react`)
- **Backend port**: 9325 | **Frontend port**: 5173
- **Tests**: 575+ tests pytest, ~37s. Pre-existing TS errors en test files (no bloqueantes)
