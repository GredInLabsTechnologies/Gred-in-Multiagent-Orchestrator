import { NextRequest, NextResponse } from "next/server";

const MAINTENANCE = process.env.MAINTENANCE_MODE?.trim() === "true";

/**
 * Dominios donde se activa el mantenimiento.
 * Ejemplo: MAINTENANCE_DOMAIN=gimo.giltech.dev
 * Si se deja vacío, se bloquean TODOS los dominios (incluyendo Vercel).
 */
const BLOCKED_DOMAINS = (process.env.MAINTENANCE_DOMAIN ?? "")
    .split(",")
    .map((d) => d.trim().toLowerCase())
    .filter(Boolean);

function isMaintenanceDomain(request: NextRequest): boolean {
    if (!MAINTENANCE) return false;

    // Si no hay dominios definidos pero MAINTENANCE_MODE es true, bloqueamos todo.
    if (BLOCKED_DOMAINS.length === 0) return true;

    const host = (request.headers.get("host") ?? "").toLowerCase();

    // Bloquear si el host coincide exactamente o es un subdominio del bloqueado.
    return BLOCKED_DOMAINS.some(
        (domain) => host === domain || host.endsWith(`.${domain}`) || host.startsWith(`${domain}:`)
    );
}

export function middleware(request: NextRequest) {
    const { pathname } = request.nextUrl;

    // 1. Rutas excluidas (Siempre accesibles)
    if (
        pathname.startsWith("/maintenance") ||
        pathname.startsWith("/_next/") ||
        pathname.startsWith("/api/auth/") ||
        pathname.match(/\.(ico|png|jpg|jpeg|svg|webp|json)$/)
    ) {
        return NextResponse.next();
    }

    // 2. Si no es un dominio bloqueado por mantenimiento, permitir acceso total
    if (!isMaintenanceDomain(request)) {
        return NextResponse.next();
    }

    // 3. En dominio bloqueado: Rutas API internas -> 503
    if (pathname.startsWith("/api/")) {
        return NextResponse.json(
            { error: "Service temporarily unavailable. Maintenance in progress." },
            { status: 503 }
        );
    }

    // 4. En dominio bloqueado: Todo lo demás (incluyendo /) -> Redirigir a /maintenance
    const url = request.nextUrl.clone();
    url.pathname = "/maintenance";
    return NextResponse.redirect(url, { status: 307 });
}

export const config = {
    matcher: [
        /*
         * Match everything except:
         * - _next/static (static files)
         * - _next/image  (image optimization)
         * - favicon.ico
         */
        "/((?!_next/static|_next/image|favicon.ico).*)",
    ],
};
