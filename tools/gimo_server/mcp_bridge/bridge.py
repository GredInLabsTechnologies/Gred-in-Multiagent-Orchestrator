import asyncio
import os
import httpx
import logging
from pathlib import Path

logger = logging.getLogger("mcp_bridge")

MAX_PROXY_RETRIES = 2
RETRY_BACKOFF = 1.0

# Default local backend URL
BACKEND_URL = "http://127.0.0.1:9325"

# Token cache: avoids reading .orch_token file on every proxy call
_token_cache: str | None = None
_token_mtime: float = 0.0
_TOKEN_FILE = Path(__file__).resolve().parent.parent / ".orch_token"


def _get_auth_token() -> str | None:
    """Read ORCH_TOKEN from env or token file with mtime-based caching."""
    global _token_cache, _token_mtime

    # Env var always wins and doesn't need caching
    token = os.environ.get("ORCH_TOKEN", "").strip()
    if token:
        return token

    # File-based token with mtime cache
    try:
        if _TOKEN_FILE.exists():
            current_mtime = _TOKEN_FILE.stat().st_mtime
            if current_mtime != _token_mtime or _token_cache is None:
                _token_cache = _TOKEN_FILE.read_text(encoding="utf-8").strip() or None
                _token_mtime = current_mtime
            return _token_cache
    except Exception:
        pass
    return None


async def proxy_to_api(method: str, path: str, **kwargs) -> str:
    """
    Generic bridge function. Formats the parameters dynamically and sends standard HTTP requests.
    """
    # Build URL by replacing path parameters like {id}
    url_path = path
    path_params = kwargs.pop("__path_params", {})
    for k, v in path_params.items():
        url_path = url_path.replace(f"{{{k}}}", str(v))

    url = f"{BACKEND_URL}{url_path}"

    query_params = kwargs.pop("__query", {})
    body = kwargs.pop("__body", None)

    # Attach auth token
    headers = {}
    token = _get_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            request = client.build_request(
                method=method,
                url=url,
                params=query_params,
                json=body,
                headers=headers,
            )
            response = await client.send(request)

            try:
                data = response.json()
                import json
                if isinstance(data, (dict, list)):
                    data_str = json.dumps(data, indent=2)
                else:
                    data_str = str(data)
            except Exception:
                data_str = response.text

            if 200 <= response.status_code < 300:
                result = f"✅ Success ({response.status_code}):\n{data_str}"
            else:
                result = f"❌ Error ({response.status_code}):\n{data_str}"

            return result

    except httpx.ConnectError:
        # Retry once after a short delay
        for attempt in range(MAX_PROXY_RETRIES):
            try:
                await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
                async with httpx.AsyncClient(timeout=30.0) as retry_client:
                    request = retry_client.build_request(
                        method=method, url=url, params=query_params, json=body, headers=headers,
                    )
                    response = await retry_client.send(request)
                    try:
                        data = response.json()
                        import json
                        data_str = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
                    except Exception:
                        data_str = response.text
                    if 200 <= response.status_code < 300:
                        return f"✅ Success ({response.status_code}):\n{data_str}"
                    return f"❌ Error ({response.status_code}):\n{data_str}"
            except httpx.ConnectError:
                continue
            except Exception as retry_err:
                logger.error(f"Bridge retry error: {retry_err}")
                break

        return (
            "❌ Connection Error: The GIMO backend is not reachable.\n"
            f"Please ensure it is running on {BACKEND_URL} or use the 'gimo_start_engine' tool."
        )
    except Exception as e:
        logger.error(f"Bridge proxy error: {e}")
        return f"❌ Bridge Error: {e}"
