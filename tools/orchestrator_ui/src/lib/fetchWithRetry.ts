/**
 * fetchWithRetry — drop-in replacement for fetch() with:
 *  - Exponential backoff retry (network errors + 5xx)
 *  - Auto-redirect to login on 401/403
 */

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 500;

export async function fetchWithRetry(
    input: RequestInfo | URL,
    init?: RequestInit,
    retries = MAX_RETRIES,
): Promise<Response> {
    let lastError: unknown;

    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            const response = await fetch(input, init);

            // Auth failure — stop retrying, redirect
            if (response.status === 401 || response.status === 403) {
                window.dispatchEvent(new CustomEvent('auth:expired'));
                return response;
            }

            // Server error — retry if attempts remain
            if (response.status >= 500 && attempt < retries) {
                await delay(BASE_DELAY_MS * 2 ** attempt);
                continue;
            }

            return response;
        } catch (err) {
            lastError = err;
            if (attempt < retries) {
                await delay(BASE_DELAY_MS * 2 ** attempt);
            }
        }
    }

    throw lastError;
}

function delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
