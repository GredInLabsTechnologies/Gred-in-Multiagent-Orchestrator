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

# Migrated from legacy_ui_router.py (deleted 2026-04-15)
router.add_api_route("/ui/hardware", _redirect("/ops/mastery/hardware"), methods=["GET"])
router.add_api_route("/ui/audit", _redirect("/ops/audit/tail"), methods=["GET"])
router.add_api_route("/ui/allowlist", _redirect("/ops/allowlist"), methods=["GET"])
router.add_api_route("/ui/cost/compare", _redirect("/ops/cost/compare"), methods=["GET"])
router.add_api_route("/ui/drafts/{draft_id}/reject", _redirect("/ops/drafts/{draft_id}/reject"), methods=["POST"])
# /ui/plan/create cannot be a transparent 308 because the contract differs
# (legacy returned {id, status, prompt, content, mermaid}; /ops/generate
# returns OpsDraft). Consumers were migrated. We still redirect for clients
# that have not updated yet — they will receive an OpsDraft.
router.add_api_route("/ui/plan/create", _redirect("/ops/generate"), methods=["POST"])
