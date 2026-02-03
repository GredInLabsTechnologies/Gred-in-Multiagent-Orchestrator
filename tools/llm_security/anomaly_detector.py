import statistics
from datetime import datetime
from typing import Dict, List


class AnomalyDetector:
    """Layer 6: Detect behavioral anomalies in LLM responses"""

    def __init__(self):
        self.history: List[Dict] = []
        self.max_history = 100

    def add_interaction(self, interaction: Dict):
        """
        Record interaction for statistical analysis.

        interaction expected format:
        {
            'input_tokens': int,
            'output_tokens': int,
            'response': str,
            'fingerprint': Optional[str],
            'violations': List[str]
        }
        """
        self.history.append(
            {
                "timestamp": datetime.now(),
                "input_tokens": interaction.get("input_tokens", 0),
                "output_tokens": interaction.get("output_tokens", 0),
                "response_length": len(interaction.get("response", "")),
                "fingerprint": interaction.get("fingerprint"),
                "violations": len(interaction.get("violations", [])),
            }
        )

        # Keep only recent history
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

    def detect_anomalies(self, current: Dict) -> List[str]:
        """
        Detect if current interaction is anomalous.
        Returns list of anomalies detected.
        """
        anomalies = []
        current_response = current.get("response", "")
        current_length = len(current_response)

        # Anomaly 4: Response too short (potential failure)
        if current_length < 50:
            anomalies.append("Response suspiciously short")

        if len(self.history) < 10:
            return anomalies  # Not enough data for statistical analysis

        # Statistical analysis on recent interactions (up to 20 for z-score)
        recent_history = self.history[-20:]
        recent_lengths = [h["response_length"] for h in recent_history]
        mean_length = statistics.mean(recent_lengths)
        stdev_length = statistics.stdev(recent_lengths) if len(recent_lengths) > 1 else 0

        # Anomaly 1: Response length significantly different (z-score > 3)
        if stdev_length > 0:
            z_score = abs((current_length - mean_length) / stdev_length)
            if z_score > 3:
                anomalies.append(f"Response length anomaly (z-score: {z_score:.2f})")

        # Anomaly 2: Fingerprint changed (model update)
        recent_fingerprints = [h["fingerprint"] for h in self.history[-10:] if h.get("fingerprint")]
        current_fingerprint = current.get("fingerprint")
        if recent_fingerprints and current_fingerprint:
            most_common_fp = max(set(recent_fingerprints), key=recent_fingerprints.count)
            if current_fingerprint != most_common_fp:
                anomalies.append(
                    f"Model fingerprint changed: {most_common_fp} → {current_fingerprint}"
                )

        # Anomaly 3: Sudden increase in violations
        recent_violations = [h["violations"] for h in self.history[-10:]]
        avg_violations = statistics.mean(recent_violations)
        current_violations = len(current.get("violations", []))
        if current_violations > avg_violations * 2 and current_violations > 0:
            anomalies.append(f"Violation spike: {current_violations} vs avg {avg_violations:.1f}")

        return anomalies

    def get_stats(self) -> Dict:
        """Get statistical summary of interactions"""
        if not self.history:
            return {
                "total_interactions": 0,
                "avg_response_length": 0.0,
                "stdev_response_length": 0.0,
                "total_violations": 0,
                "violation_rate": 0.0,
            }

        response_lengths = [h["response_length"] for h in self.history]
        violations = [h["violations"] for h in self.history]

        return {
            "total_interactions": len(self.history),
            "avg_response_length": statistics.mean(response_lengths),
            "stdev_response_length": (
                statistics.stdev(response_lengths) if len(response_lengths) > 1 else 0
            ),
            "total_violations": sum(violations),
            "violation_rate": sum(violations) / len(violations) if violations else 0,
        }
