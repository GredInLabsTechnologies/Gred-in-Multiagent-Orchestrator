from tools.llm_security.anomaly_detector import AnomalyDetector


class TestAnomalyDetector:
    def setup_method(self):
        self.detector = AnomalyDetector()

    def test_add_interaction(self):
        interaction = {
            "input_tokens": 100,
            "output_tokens": 200,
            "response": "This is a normal response that is long enough to be valid and not flagged as short.",
            "fingerprint": "fp_123",
            "violations": [],
        }
        self.detector.add_interaction(interaction)
        assert len(self.detector.history) == 1
        assert self.detector.history[0]["response_length"] == len(interaction["response"])

    def test_detect_length_anomaly(self):
        # Fill history with stable but slightly varying lengths
        # Using responses of length around 80
        for i in range(15):
            self.detector.add_interaction(
                {"response": "Normal response " + "x" * (60 + (i % 5)), "fingerprint": "fp_123"}
            )

        # Test extreme length (anomaly)
        anomalous_response = "Short"  # Also triggers short response anomaly
        anomalies = self.detector.detect_anomalies({"response": anomalous_response})
        assert any("Response length anomaly" in a for a in anomalies)
        assert "Response suspiciously short" in anomalies

    def test_detect_fingerprint_change(self):
        # Fill history with same fingerprint
        for _ in range(12):
            self.detector.add_interaction(
                {
                    "response": "Normal length response for fingerprint testing. Consistency is key.",
                    "fingerprint": "fp_123",
                }
            )

        # New fingerprint
        anomalies = self.detector.detect_anomalies(
            {
                "response": "Normal length response for fingerprint testing. Consistency is key.",
                "fingerprint": "fp_999",
            }
        )
        assert any("Model fingerprint changed" in a for a in anomalies)

    def test_detect_violation_spike(self):
        # Fill history with 0 violations
        for _ in range(12):
            self.detector.add_interaction(
                {
                    "response": "Normal response for violation testing. No violations here.",
                    "violations": [],
                }
            )

        # Spike in violations
        anomalies = self.detector.detect_anomalies(
            {
                "response": "Normal response for violation testing. But something is wrong.",
                "violations": ["v1", "v2", "v3"],
            }
        )
        assert any("Violation spike" in a for a in anomalies)

    def test_get_stats(self):
        self.detector.add_interaction({"response": "Short", "violations": ["v1"]})
        stats = self.detector.get_stats()
        assert stats["total_interactions"] == 1
        assert stats["total_violations"] == 1
        assert stats["avg_response_length"] == 5
