import asyncio
from pathlib import Path

from tools.gimo_server.services.git_service import GitService
from tools.gimo_server.providers.openai_compat import OpenAICompatAdapter


def test_git_diff_uses_ref_range(monkeypatch):
    captured = {}

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

    def _fake_popen(args, **kwargs):
        captured["args"] = args
        return _Proc()

    monkeypatch.setattr("subprocess.Popen", _fake_popen)

    out = GitService.get_diff(Path("."), base="main", head="feature/x")

    assert out == "ok"
    assert captured["args"][:3] == ["git", "diff", "--stat"]
    assert captured["args"][3] == "main..feature/x"


def test_openai_compat_reuses_async_client(monkeypatch):
    created = {"count": 0}
    sent_urls = []

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    class _Client:
        def __init__(self, timeout):
            created["count"] += 1
            self.timeout = timeout
            self.closed = False

        async def post(self, url, headers=None, json=None):
            sent_urls.append(url)
            return _Resp()

        async def get(self, url, headers=None):
            sent_urls.append(url)
            return _Resp()

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr("tools.gimo_server.providers.openai_compat.httpx.AsyncClient", _Client)

    adapter = OpenAICompatAdapter(base_url="http://localhost:11434/v1", model="qwen")

    asyncio.run(adapter.generate("hola", {}))
    asyncio.run(adapter.health_check())

    assert created["count"] == 1
    assert sent_urls[0].endswith("/chat/completions")
    assert sent_urls[1].endswith("/models")

    asyncio.run(adapter.aclose())
    asyncio.run(adapter.generate("otra", {}))
    assert created["count"] == 2


def test_mcp_bridge_does_not_instantiate_runworker():
    bridge_source = Path("tools/gimo_server/mcp_bridge/server.py").read_text(encoding="utf-8")
    assert "RunWorker" not in bridge_source
