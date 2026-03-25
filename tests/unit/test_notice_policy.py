import pytest
from tools.gimo_server.services.notice_policy_service import NoticePolicyService

def test_notice_policy_ctx_high():
    notices = NoticePolicyService.evaluate_all({"context_percentage": 75.0})
    codes = [n["code"] for n in notices]
    assert "ctx_high" in codes

def test_notice_policy_budget_high_by_percentage():
    notices = NoticePolicyService.evaluate_all({"budget_percentage": 85.0})
    codes = [n["code"] for n in notices]
    assert "budget_high" in codes

def test_notice_policy_budget_high_by_spend_limit():
    notices = NoticePolicyService.evaluate_all({"budget_spend": 85.0, "budget_limit": 100.0})
    codes = [n["code"] for n in notices]
    assert "budget_high" in codes

def test_notice_policy_new_version():
    notices = NoticePolicyService.evaluate_all({"new_version_available": True})
    codes = [n["code"] for n in notices]
    assert "new_version" in codes

def test_notice_policy_stream_down():
    notices = NoticePolicyService.evaluate_all({"stream_down": True})
    codes = [n["code"] for n in notices]
    assert "stream_down" in codes

def test_notice_policy_purge_failed():
    notices = NoticePolicyService.evaluate_all({"purge_failed": True})
    codes = [n["code"] for n in notices]
    assert "purge_failed" in codes

def test_notice_policy_merge_base_drift():
    notices = NoticePolicyService.evaluate_all({"merge_base_drift": True})
    codes = [n["code"] for n in notices]
    assert "merge_base_drift" in codes

def test_notice_policy_deterministic_no_invented_warnings():
    notices = NoticePolicyService.evaluate_all({"random_flag": True})
    assert len(notices) == 0
