import os
import httpx
import logging

logger = logging.getLogger("mcp_bridge")

# Default local backend URL
BACKEND_URL = "http://127.0.0.1:9325"


def _get_auth_token() -> str | None:
    """Read ORCH_TOKEN from env or token file (same logic as config.py)."""
    token = os.environ.get("ORCH_TOKEN", "").strip()
    if token:
        return token
    # Fallback: read from .orch_token file next to the server
    from pathlib import Path
    token_file = Path(__file__).resolve().parent.parent / ".orch_token"
    if token_file.exists():
        try:
            return token_file.read_text(encoding="utf-8").strip() or None
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
            
            # Formateamos la respuesta del backend
            try:
                data = response.json()
                data_str = str(data)
                # Pretty print if it's a dict or list
                import json
                if isinstance(data, (dict, list)):
                    data_str = json.dumps(data, indent=2)
            except Exception:
                data_str = response.text

            if 200 <= response.status_code < 300:
                result = f"✅ Success ({response.status_code}):\n{data_str}"
            else:
                result = f"❌ Error ({response.status_code}):\n{data_str}"
                
            return result
            
    except httpx.ConnectError:
        return (
            "❌ Connection Error: The GIMO backend is not reachable.\n"
            f"Please ensure it is running on {BACKEND_URL} or use the 'gimo_start_engine' tool."
        )
    except Exception as e:
        logger.error(f"Bridge proxy error: {e}")
        return f"❌ Bridge Error: {e}"
