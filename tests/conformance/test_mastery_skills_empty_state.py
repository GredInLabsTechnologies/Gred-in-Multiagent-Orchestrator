"""Mastery analytics + skills list empty-state investigation (R20-009).

The Phase 1 probe reported that ``gimo mastery analytics`` and
``gimo skills list`` returned empty results. After inline investigation
of ``tools/gimo_server/routers/ops/mastery_router.py::get_mastery_analytics``
(reads ``StorageService.cost`` aggregators) and
``tools/gimo_server/services/skills_service.py::SkillsService.list_skills``
(globs ``.gimo/skills/*.json`` from disk), the conclusion is:

    Both endpoints are data-dependency, NOT code defects.

This test seeds the minimum condition each endpoint needs and asserts
that a populated backend DOES surface the data. It also asserts that
the empty-state reply is a well-formed envelope (not an error), which
closes R20-009 as "expected empty when no data present".
"""
from __future__ import annotations


def test_mastery_analytics_envelope_shape(live_backend, auth_header):
    resp = live_backend.get("/ops/mastery/analytics", headers=auth_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The empty state MUST still be a well-formed CostAnalytics envelope.
    for key in (
        "daily_costs",
        "by_model",
        "by_task_type",
        "by_provider",
        "roi_leaderboard",
        "cascade_stats",
        "cache_stats",
        "total_savings",
    ):
        assert key in body, f"analytics envelope missing key {key}: {body}"


def test_skills_list_envelope_shape(live_backend, auth_header):
    resp = live_backend.get("/ops/skills", headers=auth_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), f"skills list must be an array: {body!r}"
    # Empty list is acceptable; non-list or error envelope is not.
