"""Legacy 308 redirects from old paths to /ops/* canonical endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

router = APIRouter(tags=["redirects"])


def _redirect(new_path: str):
    async def handler(request: Request, **kw):
        qs = str(request.url.query)
        target = new_path + (f"?{qs}" if qs else "")
        return RedirectResponse(url=target, status_code=308, headers={"Deprecation": "true"})
    return handler


router.add_api_route("/ui/repos", _redirect("/ops/repos"), methods=["GET"])
router.add_api_route("/ui/repos/register", _redirect("/ops/repos/register"), methods=["POST"])
router.add_api_route("/ui/repos/active", _redirect("/ops/repos/active"), methods=["GET"])
router.add_api_route("/ui/repos/open", _redirect("/ops/repos/open"), methods=["POST"])
router.add_api_route("/ui/repos/select", _redirect("/ops/repos/select"), methods=["POST"])
router.add_api_route("/ui/repos/revoke", _redirect("/ops/repos/revoke"), methods=["POST"])
router.add_api_route("/ui/graph", _redirect("/ops/graph"), methods=["GET"])
router.add_api_route("/ui/security/events", _redirect("/ops/security/events"), methods=["GET"])
router.add_api_route("/ui/security/resolve", _redirect("/ops/security/resolve"), methods=["POST"])
router.add_api_route("/ui/service/status", _redirect("/ops/service/status"), methods=["GET"])
router.add_api_route("/ui/service/restart", _redirect("/ops/service/restart"), methods=["POST"])
router.add_api_route("/ui/service/stop", _redirect("/ops/service/stop"), methods=["POST"])
router.add_api_route("/ui/repos/vitaminize", _redirect("/ops/repos/vitaminize"), methods=["POST"])
router.add_api_route("/tree", _redirect("/ops/files/tree"), methods=["GET"])
router.add_api_route("/file", _redirect("/ops/files/content"), methods=["GET"])
router.add_api_route("/search", _redirect("/ops/files/search"), methods=["GET"])
router.add_api_route("/diff", _redirect("/ops/files/diff"), methods=["GET"])
