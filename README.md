# MACT Petition Drafter

Autonomous pipeline that ingests motor-accident case documents, maintains a
self-consistent knowledge base (`knowledge/case_record.json`), and drafts a
compensation petition grounded in Indian Supreme Court precedent.

## Quick start
```
pip install -r requirements.txt
python src/ingest.py --stream medical --file synthetic/medical/discharge_summary.txt
python src/reconcile.py
python src/verify_kb.py          # uses a fresh LLM context
python src/draft_petition.py
python src/verify_petition.py    # independent grader
```

## Directory layout
```
/data/              ← GITIGNORED — real case documents only
/synthetic/         ← fake docs for demo / CI
/precedent/         ← case-law notes (Sarla Verma, Pranay Sethi, Kavin Singh)
/rubric/            ← kb_invariants.md, petition_rubric.md
/knowledge/         ← case_record.json, changelog.md (generated)
/src/               ← pipeline modules
/logs/              ← verifier exchange transcripts
```

## Commit policy
A reconcile cycle commits `case_record.json` **only** when the KB verifier
returns PASS. All verifier exchanges are logged to `/logs/`.
