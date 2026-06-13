# verify-release

> Pre-release gate: fan out 5 independent verification agents in parallel, then
> synthesize a single PASS / FAIL release-readiness verdict.

Run all five checks below **in parallel** using the Task tool. Each agent runs
independently with no shared state. After all five complete, produce a
synthesis report.

---

## Agent 1 — selftest

Run the deterministic self-test suite:

```bash
cd /Users/harikrishna/dev/ClaudeDevDay && python -m scripts.selftest
```

**Pass condition:** exit code 0 AND stdout contains `ALL CHECKS PASSED`.

---

## Agent 2 — itest

Run the integration test (stubs LLM calls, validates full pipeline + SSE
event wiring):

```bash
cd /Users/harikrishna/dev/ClaudeDevDay && python -m scripts.itest
```

**Pass condition:** exit code 0 AND stdout contains `ALL INTEGRATION CHECKS PASSED`.

---

## Agent 3 — rubric-auditor

Use the `.claude/agents/rubric-auditor.md` agent definition.

Read these files:
- `knowledge/case_record.json`
- `knowledge/petition_draft.md`
- `rubric/kb_invariants.md`
- `rubric/petition_rubric.md`

Grade every MUST item in both rubrics against the current artifacts.

**Pass condition:** every MUST item grades PASS.

---

## Agent 4 — deploy-checker

Verify the deployed instance at `https://mact-petition-drafter.onrender.com`
responds correctly. Curl each endpoint:

```bash
curl -sf https://mact-petition-drafter.onrender.com/api/health
curl -sf https://mact-petition-drafter.onrender.com/api/corpus
curl -sf https://mact-petition-drafter.onrender.com/api/state
curl -sf https://mact-petition-drafter.onrender.com/api/replay
```

**Pass condition:** all return HTTP 200 with non-null JSON bodies. The health
endpoint should report `api_key_present` (true or false is fine — it confirms
the server is live). The replay endpoint should contain `record` and `draft`
keys with non-null values.

---

## Agent 5 — adversarial-verifier

Use the `.claude/agents/adversarial-verifier.md` agent definition.

Read the petition draft (`knowledge/petition_draft.md`) and the KB
(`knowledge/case_record.json`) independently. Check for:

1. **Untraceable facts** — any factual claim in the petition that cannot be
   traced to an active KB fact via its `[F##]` citation.
2. **Arithmetic errors** — re-derive loss of future earning, medical expenses,
   and grand total from KB values; compare to petition claims.

**Pass condition:** zero violations found.

---

## Synthesis

After all 5 agents report back, produce a summary table:

```
| Agent               | Result | Details                    |
|---------------------|--------|----------------------------|
| selftest            | PASS   | 14/14 checks passed        |
| itest               | PASS   | happy + injected paths OK  |
| rubric-auditor      | PASS   | all MUSTs pass             |
| deploy-checker      | PASS   | 4/4 endpoints 200          |
| adversarial-verifier| PASS   | 0 violations               |
```

**Overall verdict: PASS** (all 5 pass) or **FAIL** (any agent fails — list
the failing agents and their failure details).
