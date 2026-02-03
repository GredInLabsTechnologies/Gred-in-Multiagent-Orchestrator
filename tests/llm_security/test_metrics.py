import pytest

from tools.llm_security.metrics import LLMMetrics


class TestLLMMetrics:
    def setup_method(self):
        self.metrics = LLMMetrics()

    def test_metrics_tracking(self):
        self.metrics.track_interaction(success=True)
        self.metrics.track_interaction(success=False, aborted=True, layer_failed="layer1")
        self.metrics.track_security_event("injection")
        self.metrics.track_security_event("anomaly")

        assert self.metrics.total_interactions == 2
        assert self.metrics.successful_interactions == 1
        assert self.metrics.aborted_interactions == 1
        assert self.metrics.layer_failures["layer1"] == 1
        assert self.metrics.detected_injections == 1
        assert self.metrics.anomalies_detected == 1

    def test_cost_calculation(self):
        usage = {"prompt_tokens": 1000, "completion_tokens": 1000}
        cost = self.metrics.calculate_cost(usage)
        assert cost == pytest.approx(0.04)
        assert self.metrics.total_cost_usd == pytest.approx(0.04)
        assert self.metrics.total_tokens_used == 2000

    def test_export_metrics(self):
        self.metrics.track_interaction(success=True)
        data = self.metrics.export_metrics()
        assert "timestamp" in data
        assert data["summary"]["total_interactions"] == 1
        assert "security" in data
        assert "usage" in data

    def test_threshold_alerts(self):
        # Trigger injection alert
        for _ in range(6):
            self.metrics.track_security_event("injection")

        # Trigger cost alert
        usage = {"prompt_tokens": 5000000, "completion_tokens": 1000}  # Very high input
        self.metrics.calculate_cost(usage)

        # Trigger abort rate alert (need at least 11 interactions)
        for _ in range(8):
            self.metrics.track_interaction(success=False, aborted=True)
        for _ in range(4):
            self.metrics.track_interaction(success=True)

        alerts = self.metrics.check_thresholds()
        assert any("Injection attempts" in alert for alert in alerts)
        assert any("Daily cost" in alert for alert in alerts)
        assert any("Abort rate" in alert for alert in alerts)
