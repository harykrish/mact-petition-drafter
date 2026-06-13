# Petition verification — 2026-06-13T18:49:11Z

Result: **revise**

## Independent arithmetic (re-derived from the KB)
- Loss of future earning: **84500000** — 6500000 x (1+0.25) x 13 x 80% = 84500000
- Medical expenses: **5000000** — 2000000 + 400000 + 600000 + 1500000 + 500000 = 5000000
- Petition claimed: `{"loss_of_earning": 93600000, "medical_expenses": 5000000, "heads": {"Loss of future earning capacity": 93600000, "Medical expenses": 5000000, "Pain and suffering": 100000}, "grand_total": 98700000}`

## MUST
- [ ] **M8** (FAIL) — petition claims 93600000; re-derived 84500000 (6500000 x (1+0.25) x 13 x 80% = 84500000)
- [x] **M9** (PASS) — medical expenses 5000000 matches sum of bills (2000000 + 400000 + 600000 + 1500000 + 500000 = 5000000)
- [x] **M10** (PASS) — grand total 98700000 == sum of heads 98700000
- [x] **M1** (PASS) — graded by fresh-context LLM verifier
- [x] **M2** (PASS) — graded by fresh-context LLM verifier
- [x] **M3** (PASS) — graded by fresh-context LLM verifier
- [x] **M4** (PASS) — graded by fresh-context LLM verifier
- [x] **M5** (PASS) — graded by fresh-context LLM verifier
- [x] **M6** (PASS) — graded by fresh-context LLM verifier
- [x] **M7** (PASS) — graded by fresh-context LLM verifier
- [x] **M11** (PASS) — graded by fresh-context LLM verifier
- [x] **M12** (PASS) — graded by fresh-context LLM verifier
- [x] **M13** (PASS) — graded by fresh-context LLM verifier

## Feedback to drafter
M8: loss of future earning should be 84500000, computed as 6500000 x (1+0.25) x 13 x 80% = 84500000. You wrote 93600000.
