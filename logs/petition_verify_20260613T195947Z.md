# Petition verification — 2026-06-13T19:59:47Z

Result: **pass**

## Independent arithmetic (re-derived from the KB)
- Loss of future earning: **93600000** — 7200000 x (1+0.25) x 13 x 80% = 93600000
- Medical expenses: **5000000** — 400000 + 600000 + 2000000 + 500000 + 1500000 = 5000000
- Petition claimed: `{"loss_of_earning": 93600000, "medical_expenses": 5000000, "heads": {"loss_of_future_earning_capacity": 93600000, "medical_expenses_incurred": 5000000, "loss_of_income_during_treatment": 887671, "attendant_nursing_charges": 1500000, "future_medical_rehabilitation": 1500000, "pain_suffering_trauma": 500000, "loss_of_amenities": 500000, "special_diet_conveyance": 200000}, "grand_total": 103687671}`

## MUST
- [x] **M8** (PASS) — loss of earning 93600000 matches re-derivation (7200000 x (1+0.25) x 13 x 80% = 93600000)
- [x] **M9** (PASS) — medical expenses 5000000 matches sum of bills (400000 + 600000 + 2000000 + 500000 + 1500000 = 5000000)
- [x] **M10** (PASS) — grand total 103687671 == sum of heads 103687671
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
Verifier: All MUST and SHOULD items pass. Parsed and independently recomputed every amount: loss of future earning 93,600,000 (7,200,000 x 1.25 x 13 x 0.80), medical 5,000,000, grand total 103,687,671 — all match to the rupee. Multiplier (13) and future prospects (+25%) correct for age 48 self-employed. Income from financial stream, disability from medical stream, liability from police stream. Disputed accident date properly flagged, not asserted as settled. Minor note for cleanup: F015 is cited in para 3.2 but is not present in the active fact set — since it is used only to describe the disclosed contradiction it does not ground any claim, but confirm the reference before filing.
