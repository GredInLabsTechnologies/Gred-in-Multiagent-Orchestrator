import glob
import json
import os
from datetime import datetime


class ReportBuilder:
    def __init__(self, metrics_dir="out/metrics"):
        self.metrics_dir = metrics_dir
        self.results = []
        self.summary = {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "panics_triggered": 0,
            "bypasses_detected": 0,
            "avg_latency": 0,
        }

    def load_metrics(self):
        """Loads all JSON report files from the metrics directory."""
        files = glob.glob(os.path.join(self.metrics_dir, "*_report.json"))
        for f in files:
            if "final_report.json" in f:
                continue
            try:
                with open(f, "r") as file:
                    data = json.load(file)
                    # Handle both list of results or summary dict structure
                    if isinstance(data, dict) and "results" in data:
                        self.results.extend(data["results"])
                    elif isinstance(data, list):
                        self.results.extend(data)
            except Exception as e:
                print(f"Error loading {f}: {e}")

    def analyze(self):
        """Aggregates statistics from loaded results."""
        if not self.results:
            return

        total_latency = 0
        for r in self.results:
            self.summary["total_tests"] += 1
            total_latency += r.get("latency_ms", 0)

            if r.get("panic_triggered"):
                self.summary["panics_triggered"] += 1

            if r.get("bypassed"):
                self.summary["bypasses_detected"] += 1
                self.summary["failed"] += 1
            else:
                # Assuming simple pass if not bypassed,
                # strictly speaking we might have other fail conditions
                self.summary["passed"] += 1

        if self.summary["total_tests"] > 0:
            self.summary["avg_latency"] = total_latency / self.summary["total_tests"]

    def generate_markdown(self, output_path="out/metrics/security_report.md"):
        """Generates a human-readable Markdown report."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        md = "# Gred Orchestrator Security Test Report\n"
        md += f"**Date:** {timestamp}\n\n"

        md += "## Executive Summary\n"
        md += "| Metric | Value | Status |\n"
        md += "|---|---|---|\n"
        md += f"| Total Tests | {self.summary['total_tests']} | - |\n"
        md += f"| **Critical Bypasses** | {self.summary['bypasses_detected']} | {'❌ FAIL' if self.summary['bypasses_detected'] > 0 else '✅ PASS'} |\n"
        md += f"| Panics Triggered | {self.summary['panics_triggered']} | {'⚠️ WARN' if self.summary['panics_triggered'] > 0 else 'ℹ️ INFO'} |\n"
        md += f"| Avg Latency | {self.summary['avg_latency']:.2f} ms | - |\n\n"

        md += "## Detailed Findings\n"
        if self.summary["bypasses_detected"] > 0:
            md += "### 🚨 CRITICAL VULNERABILITIES DETECTED\n"
            for r in self.results:
                if r.get("bypassed"):
                    md += f"- **Endpoint:** `{r.get('target_endpoint')}`\n"
                    md += f"  - **Payload:** `{r.get('payload')}`\n"
                    md += f"  - **Status:** {r.get('status_code')}\n\n"
        else:
            md += "No critical bypasses were found during this run.\n"

        md += "\n### Test Coverage\n"
        suites = set(r.get("suite", "unknown") for r in self.results)
        for s in suites:
            count = sum(1 for r in self.results if r.get("suite") == s)
            md += f"- **{s}**: {count} vectors tested\n"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md)
        return output_path


if __name__ == "__main__":
    builder = ReportBuilder()
    builder.load_metrics()
    builder.analyze()
    path = builder.generate_markdown()
    print(f"Report generated at: {os.path.abspath(path)}")
