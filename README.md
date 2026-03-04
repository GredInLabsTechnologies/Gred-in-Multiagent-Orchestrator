# GIMO WEB

Landing de GIMO construida con:

- **Next.js (App Router + TypeScript + Tailwind)**
- **Firebase Auth (Google Sign-In)** para autenticación
- **Vercel** para despliegue

## 1) Instalación

```bash
npm install
```

## 2) Variables de entorno

Copia el ejemplo y completa valores:

```bash
copy .env.example .env.local
```

Variables necesarias:

- `NEXT_PUBLIC_FIREBASE_API_KEY`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
- `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`
- `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`
- `NEXT_PUBLIC_FIREBASE_APP_ID`
- `FIREBASE_ADMIN_SERVICE_ACCOUNT` (JSON de service account en una sola línea o base64)
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_STANDARD_PRICE_ID`
- `LICENSE_SIGNING_PRIVATE_KEY` (Ed25519 PKCS8 PEM con `\n` escapados)

## 2.1) Seguridad de licencias (token blindado por entitlement)

Flujo de seguridad implementado:

1. `POST /api/license/validate` **solo firma token** si la licencia cumple entitlement.
2. Entitlement valida:
   - licencia no revocada/expirada,
   - y para no-lifetime: suscripción Stripe asociada en estado permitido (`active`/`trialing`) y periodo vigente.
3. Si entitlement falla:
   - se deniega token (`403`),
   - se reconcilia estado de licencia,
   - y se desactivan activaciones activas (fail-safe).
4. Webhooks Stripe sincronizan estado de suscripción y licencia:
   - `checkout.session.completed` => licencia `pending_payment`
   - `invoice.paid` => licencia `active` (si corresponde)
   - `invoice.payment_failed` => licencia `suspended`
   - `customer.subscription.updated/deleted` => sincronización + corte de activaciones si no está activa

Endpoint admin adicional:

- `POST /api/admin/license/reconcile` (admin only): revalida consistencia de licencias no-lifetime.

## 3) Arrancar en local

```bash
npm run dev
```

- Web: `http://localhost:3000`

## 4) Firebase Auth con Google (sprint mode 🚀)

1. Ve a [Firebase Console](https://console.firebase.google.com/) y crea proyecto.
2. En **Authentication > Sign-in method**, activa **Google**.
3. En **Project settings > Your apps**, registra app web y copia credenciales.
4. Pega las credenciales en `.env.local` usando las variables `NEXT_PUBLIC_FIREBASE_*`.
5. En Firebase Auth, añade tus dominios autorizados:
   - `localhost`
   - `127.0.0.1`
   - tu dominio de Vercel (`*.vercel.app` o dominio custom)
Con eso funcionarán:

- el botón **Sign in Google** del navbar
- la página **/empezar-gratis** con acceso por Google

## 5) Deploy en Vercel

1. Importa el repo en Vercel usando esta URL:

   `https://github.com/Shiloren/GIMO-WEB`

   > En Vercel: **Add New... > Project > Import Git Repository**.
2. Añade las mismas variables de entorno de `.env.local` en **Project Settings > Environment Variables**.
3. Deploy.

## Scripts

- `npm run dev` → desarrollo
- `npm run build` → build producción
- `npm run start` → arranque producción
- `npm run lint` → lint

## Validación manual recomendada (go-live)

Antes de pasar a producción con Stripe real:

1. Crear checkout de prueba y confirmar que la licencia nace en `pending_payment`.
2. Simular `invoice.paid` y verificar transición a `active`.
3. Simular `invoice.payment_failed` y verificar:
   - licencia `suspended`,
   - desactivación de activaciones,
   - `/api/license/validate` devuelve `403` sin token.
4. Simular `customer.subscription.deleted` y verificar licencia no usable.
5. Ejecutar reconciliación admin y comprobar que corrige inconsistencias:
   - `POST /api/admin/license/reconcile`.
