import json
import os
import time
from dataclasses import asdict, dataclass
from typing import List


@dataclass
class TestResult:
    suite: str
    target_endpoint: str
    payload: str
    status_code: int
    latency_ms: float
    panic_triggered: bool
    bypassed: bool
    timestamp: float


class MetricsCollector:
    def __init__(self):
        self.results: List[TestResult] = []
        self.start_time = time.time()

    def add_result(
        self,
        suite: str,
        endpoint: str,
        payload: str,
        status: int,
        latency: float,
        panic: bool,
        bypassed: bool,
    ):
        result = TestResult(
            suite=suite,
            target_endpoint=endpoint,
            payload=payload,
            status_code=status,
            latency_ms=latency * 1000,
            panic_triggered=panic,
            bypassed=bypassed,
            timestamp=time.time(),
        )
        self.results.append(result)

    def save_report(self, filepath: str = "out/metrics/final_report.json"):
        summary = {
            "total_tests": len(self.results),
            "panic_count": sum(1 for r in self.results if r.panic_triggered),
            "bypass_count": sum(1 for r in self.results if r.bypassed),
            "avg_latency_ms": (
                sum(r.latency_ms for r in self.results) / len(self.results) if self.results else 0
            ),
            "duration_sec": time.time() - self.start_time,
            "results": [asdict(r) for r in self.results],
        }

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(summary, f, indent=4)
        return summary
