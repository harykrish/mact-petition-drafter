"""Paths, model id, and the reconciliation knobs shared across the pipeline."""
from __future__ import annotations

import os
from pathlib import Path

# --- Model ---------------------------------------------------------------
# Pinned per the brief. Override only via env if you must.
MODEL = os.environ.get("MACT_MODEL", "claude-opus-4-8")

# --- Paths ---------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"            # gitignored — real documents
SYNTHETIC_DIR = BASE_DIR / "synthetic"  # fake demo corpus
PRECEDENT_DIR = BASE_DIR / "precedent"
RUBRIC_DIR = BASE_DIR / "rubric"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
LOGS_DIR = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "output"

CASE_RECORD_PATH = KNOWLEDGE_DIR / "case_record.json"
CHANGELOG_MD_PATH = KNOWLEDGE_DIR / "changelog.md"
PETITION_PATH = OUTPUT_DIR / "petition_draft.md"

KB_INVARIANTS_PATH = RUBRIC_DIR / "kb_invariants.md"
PETITION_RUBRIC_PATH = RUBRIC_DIR / "petition_rubric.md"

VALID_STREAMS = ("medical", "police", "financial")

# --- Reconciliation ------------------------------------------------------
# Canonical fields the extractor should use. The reconciler keys on these.
# Itemised medical costs use "medical_expense_<slug>" (summed by the verifier).
CANONICAL_FIELDS = {
    "victim_name": "Full legal name of the injured/claimant.",
    "victim_age": "Age in years at the time of the accident (integer).",
    "accident_date": "Date of the accident, ISO format YYYY-MM-DD.",
    "accident_place": "Where the accident occurred.",
    "offending_vehicle": "Registration/description of the at-fault vehicle.",
    "offending_driver": "Name of the driver of the offending vehicle.",
    "vehicle_owner": "Registered owner of the offending vehicle.",
    "insurer": "Insurance company of the offending vehicle.",
    "policy_number": "Insurance policy number of the offending vehicle.",
    "negligence": "Short statement of how the accident was caused (liability).",
    "injuries": "Nature of injuries sustained.",
    "hospitalization_days": "Number of in-patient days (integer).",
    "functional_disability_pct": "Permanent functional/earning-capacity disability, percent (integer).",
    "permanent_disability": "Whether disability is permanent (yes/no) and its description.",
    "occupation": "Occupation of the claimant.",
    "employment_type": "One of: salaried_permanent, self_employed, fixed_wage.",
    "annual_income": "Gross annual income in INR (integer rupees).",
    # medical_expense_<slug>: one fact per itemised hospital-bill line (INR integer).
}

# Per-source-type authority weight (0..1). Drives correction vs contradiction.
SOURCE_AUTHORITY = {
    "FIR": 0.90,
    "Charge Sheet": 0.95,
    "Discharge Summary": 0.85,
    "Disability Assessment Certificate": 0.95,
    "Hospital Bill": 0.90,
    "Salary Slip": 0.80,
    "Form 16": 0.95,
    "ITR": 0.95,
}
DEFAULT_AUTHORITY = 0.85

# If two conflicting values differ in authority by at least this much, the
# higher one is treated as a CORRECTION. Otherwise it's a CONTRADICTION
# (parked for a human — never silently resolved).
CORRECTION_MARGIN = 0.10

# Fields treated as numeric / date for value comparison.
NUMERIC_FIELDS = {"victim_age", "hospitalization_days", "functional_disability_pct", "annual_income"}
DATE_FIELDS = {"accident_date"}
# Name-like fields use initial-aware token matching (so "Ramesh K. Sharma"
# and "Ramesh Kumar Sharma" are the same fact, not a contradiction).
NAME_FIELDS = {"victim_name", "offending_driver", "vehicle_owner"}

# Narrative/descriptive fields: multiple sources can each contribute a phrasing
# without conflicting. Differing values are appended (corroboration), never
# flagged as contradictions, and are exempt from the single-active-fact rule.
NARRATIVE_FIELDS = {"injuries", "negligence", "accident_place", "permanent_disability"}

NEEDS_REVIEW_BELOW = 0.80
