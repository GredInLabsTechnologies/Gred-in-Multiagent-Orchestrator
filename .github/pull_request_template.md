## Summary

Describe what changed and why.

## Checklist

- [ ] `pre-commit run --all-files` passes
- [ ] `python scripts/ci/quality_gates.py` passes
- [ ] `python -m pytest -m "not integration"` passes
- [ ] UI: `npm ci && npm run lint && npm run test:coverage && npm run build` (if UI touched)
- [ ] LLM/adversarial suites validated (CI job `llm-adversarial`)

## Risk / notes

- Any security-impacting changes?
- Any repo policy changes (artifacts, tmp, logs)?
