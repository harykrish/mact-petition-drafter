# MACT Petition Drafter — Project Brief

**Goal:** Autonomously compress weeks of paralegal work into a single pipeline:
ingest case documents → maintain a self-consistent knowledge base → draft a
Motor Accident Claims Tribunal (MACT) petition → verify it against rubrics.

**Jurisdiction:** India — Motor Vehicles Act 1988, governed by Supreme Court
precedents including Sarla Verma (2009), Pranay Sethi (2017), and Kavin Singh (2024).

**Key design constraint:** `case_record.json` is the single source of truth.
The petition drafter reads ONLY from it; no agent may read raw documents
during drafting.
