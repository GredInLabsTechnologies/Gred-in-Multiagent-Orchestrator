from __future__ import annotations
import asyncio
from ..contracts import StageInput, StageOutput, ExecutionStage

class QaGate(ExecutionStage):
    name = "qa_gate"

    async def execute(self, input: StageInput) -> StageOutput:
        test_command = input.context.get("test_command", "npm test")
        timeout = float(input.context.get("qa_timeout_seconds", 120))

        proc = await asyncio.create_subprocess_shell(
            str(test_command),
            cwd=input.context.get("workspace_root") or None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return StageOutput(
                status="fail",
                artifacts={"qa_verdict": "TIMEOUT", "qa_command": test_command},
                error=f"QA timeout after {timeout}s: {test_command}",
            )

        out = (stdout or b"").decode("utf-8", errors="replace")
        err = (stderr or b"").decode("utf-8", errors="replace")
        ok = proc.returncode == 0

        if ok:
            return StageOutput(
                status="continue",
                artifacts={
                    "qa_verdict": "PASS", "qa_command": test_command,
                    "qa_return_code": 0,
                    "qa_stdout_tail": out[-2000:], "qa_stderr_tail": err[-2000:],
                },
            )
        return StageOutput(
            status="fail",
            artifacts={
                "qa_verdict": "FAIL", "qa_command": test_command,
                "qa_return_code": proc.returncode,
                "qa_stdout_tail": out[-2000:], "qa_stderr_tail": err[-2000:],
            },
            error=f"QA failed (exit {proc.returncode}): {err[-500:]}" if err else f"QA failed (exit {proc.returncode})",
        )

    async def rollback(self, input: StageInput) -> None:
        pass
