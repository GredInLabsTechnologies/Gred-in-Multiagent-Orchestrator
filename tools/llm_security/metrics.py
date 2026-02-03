from datetime import datetime
from typing import Dict, List, Optional


class LLMMetrics:
    """Track and report operational metrics for LLM integration."""

    def __init__(self):
        self.total_interactions = 0
        self.successful_interactions = 0
        self.aborted_interactions = 0
        self.layer_failures: Dict[str, int] = {}
        self.detected_injections = 0
        self.detected_secrets = 0
        self.anomalies_detected = 0
        self.total_tokens_used = 0
        self.total_cost_usd = 0.0

        # Thresholds
        self.injection_threshold = 5  # per hour (simplified for now as total in this instance)
        self.cost_threshold = 50.0  # per day (simplified as total in this instance)
        self.anomaly_rate_threshold = 0.1
        self.abort_rate_threshold = 0.2

    def calculate_cost(self, usage: Dict) -> float:
        """
        Calculate cost based on GPT-4 Turbo pricing.
        Input: $0.01 / 1K tokens
        Output: $0.03 / 1K tokens
        """
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        cost = (input_tokens / 1000 * 0.01) + (output_tokens / 1000 * 0.03)
        self.total_cost_usd += cost
        self.total_tokens_used += input_tokens + output_tokens
        return cost

    def track_interaction(
        self, success: bool, aborted: bool = False, layer_failed: Optional[str] = None
    ):
        """Track basic interaction status."""
        self.total_interactions += 1
        if success:
            self.successful_interactions += 1
        if aborted:
            self.aborted_interactions += 1
        if layer_failed:
            self.layer_failures[layer_failed] = self.layer_failures.get(layer_failed, 0) + 1

    def track_security_event(self, type: str):
        """Track specific security events."""
        if type == "injection":
            self.detected_injections += 1
        elif type == "secret":
            self.detected_secrets += 1
        elif type == "anomaly":
            self.anomalies_detected += 1

    def export_metrics(self) -> Dict:
        """Export metrics in JSON-serializable format."""
        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_interactions": self.total_interactions,
                "successful_interactions": self.successful_interactions,
                "aborted_interactions": self.aborted_interactions,
                "success_rate": (
                    self.successful_interactions / self.total_interactions
                    if self.total_interactions > 0
                    else 0
                ),
            },
            "security": {
                "detected_injections": self.detected_injections,
                "detected_secrets": self.detected_secrets,
                "anomalies_detected": self.anomalies_detected,
                "layer_failures": self.layer_failures,
            },
            "usage": {
                "total_tokens": self.total_tokens_used,
                "total_cost_usd": round(self.total_cost_usd, 4),
            },
            "alerts": self.check_thresholds(),
        }

    def check_thresholds(self) -> List[str]:
        """Check if any metric exceeds defined safety thresholds."""
        alerts = []

        if self.detected_injections > self.injection_threshold:
            alerts.append(
                f"HIGH: Injection attempts ({self.detected_injections}) exceed threshold ({self.injection_threshold})"
            )

        if self.total_cost_usd > self.cost_threshold:
            alerts.append(
                f"MEDIUM: Daily cost ({self.total_cost_usd:.2f}) exceeds threshold ({self.cost_threshold:.2f})"
            )

        if self.total_interactions > 10:
            anomaly_rate = self.anomalies_detected / self.total_interactions
            if anomaly_rate > self.anomaly_rate_threshold:
                alerts.append(
                    f"LOW: Anomaly rate ({anomaly_rate:.2%}) exceeds threshold ({self.anomaly_rate_threshold:.2%})"
                )

            abort_rate = self.aborted_interactions / self.total_interactions
            if abort_rate > self.abort_rate_threshold:
                alerts.append(
                    f"HIGH: Abort rate ({abort_rate:.2%}) exceeds threshold ({self.abort_rate_threshold:.2%})"
                )

        return alerts
