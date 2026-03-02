# GIMO WEB — Guia de Despliegue y Mantenimiento

## URLs

| URL | Proposito |
|-----|-----------|
| `gimo.giltech.dev` | Dominio publico (pasa por Cloudflare) |
| `gimo-web.vercel.app` | URL directa de Vercel (NO pasa por Cloudflare) |
| `https://vercel.com/jcs-projects-b7e90e98/gimo-web` | Dashboard del proyecto |

## Arquitectura de red

```
Usuario --> Cloudflare (DNS + Access) --> Vercel --> GIMO WEB (Next.js)
Backend orchestrator --> gimo-web.vercel.app --> Vercel --> GIMO WEB (directo, sin Cloudflare)
```

**Importante:** El backend del orchestrator siempre debe usar `gimo-web.vercel.app` (no `gimo.giltech.dev`) para evitar que Cloudflare Access bloquee las llamadas API server-to-server.

---

## Modo Mantenimiento

### Activar mantenimiento
El modo mantenimiento se controla desde el codigo de GIMO WEB (Next.js), no desde Vercel ni Cloudflare.

Opciones tipicas:
1. **Variable de entorno**: Anadir `NEXT_PUBLIC_MAINTENANCE=true` en Vercel env vars y redesplegar
2. **Ruta de mantenimiento**: Si existe `/maintenance` como pagina estatica, redirigir todo el trafico ahi via `next.config.js` o middleware de Next.js

### Desactivar mantenimiento
1. Quitar o poner en `false` la variable `NEXT_PUBLIC_MAINTENANCE`
2. Redesplegar: Deployments > ultimo deploy > menu ... > Redeploy

### CUIDADO
- Activar mantenimiento NO afecta las rutas `/api/*` a menos que el middleware lo haga explicitamente
- Verificar que `/api/orchestrator/verify` sigue respondiendo aunque el frontend este en mantenimiento

---

## Cloudflare Access (Proteger la web)

Dashboard: https://one.dash.cloudflare.com > Access > Applications

### Configuracion actual
- `orch.giltech.dev` — protegido con 3 policies
- `gimo.giltech.dev` — proteger con policy de email personal

### Anadir proteccion a gimo.giltech.dev
1. Access > Applications > + Add an application > Self-hosted
2. Application name: `gimo.giltech.dev`
3. Application domain: `gimo.giltech.dev`
4. Policy: Allow, Include > Emails > tu email
5. Guardar

### Quitar proteccion (cuando la web este lista)
1. Access > Applications > gimo.giltech.dev > menu ... > Delete
2. O editar y cambiar la policy a Allow > Everyone

---

## Variables de entorno

### En Vercel (GIMO WEB)
| Variable | Valor | Notas |
|----------|-------|-------|
| `GIMO_INTERNAL_KEY` | `gimo_local_dev_secret_2026` | Requerida para que el orchestrator valide Firebase tokens |
| `NEXT_PUBLIC_FIREBASE_*` | (config Firebase) | Ya configuradas |
| `FIREBASE_ADMIN_SERVICE_ACCOUNT` | (JSON) | Para verificar tokens server-side |

### En el orchestrator (.env local)
| Variable | Valor | Notas |
|----------|-------|-------|
| `GIMO_WEB_URL` | `https://gimo-web.vercel.app` | Siempre la URL directa de Vercel |
| `GIMO_INTERNAL_KEY` | `gimo_local_dev_secret_2026` | Debe coincidir con Vercel |

**CRITICO:** Ambas `GIMO_INTERNAL_KEY` deben ser identicas. Si cambias una, cambia la otra.

---

## Flujo de Login con Google

```
1. Frontend (Firebase popup) --> usuario se autentica con Google
2. Frontend obtiene idToken de Firebase
3. Frontend --> POST /auth/firebase-login { idToken }
4. Backend orchestrator --> POST gimo-web.vercel.app/api/orchestrator/verify
   Headers: { X-Internal-Key: GIMO_INTERNAL_KEY }
   Body: { idToken }
5. GIMO WEB valida el token con Firebase Admin SDK
6. GIMO WEB responde con: { email, displayName, role, license, subscription }
7. Backend crea sesion (cookie httpOnly)
8. Usuario autenticado
```

### Si el login falla, verificar en orden:
1. GIMO WEB esta desplegado? --> visitar `gimo-web.vercel.app`
2. `GIMO_INTERNAL_KEY` existe en Vercel env vars? --> Settings > Environment Variables
3. Las keys coinciden? --> comparar `.env` local con Vercel
4. El endpoint responde? --> `curl -X POST gimo-web.vercel.app/api/orchestrator/verify` (debe dar 400/401, no 404/503)
5. Cloudflare Access bloquea? --> usar URL `.vercel.app`, no el dominio custom

---

## Redesplegar sin downtime

Vercel hace deploys atomicos (zero-downtime):
1. Push a main --> deploy automatico
2. O manual: Deployments > Redeploy

No hace falta modo mantenimiento para desplegar cambios normales.

### Cuando SI usar mantenimiento
- Migraciones de base de datos que rompen compatibilidad
- Cambios de esquema en Firestore/Firebase que afectan a usuarios activos
- Nunca para cambios normales de UI o API

---

## Checklist pre-deploy

- [ ] `GIMO_INTERNAL_KEY` configurada y coincide con orchestrator
- [ ] Firebase env vars presentes
- [ ] `/api/orchestrator/verify` responde (405 en GET = OK)
- [ ] Cloudflare Access configurado si quieres privacidad
- [ ] Orchestrator apunta a `gimo-web.vercel.app` (no al dominio custom)
