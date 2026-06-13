"""Paths, model id, and the reconciliation knobs shared across the pipeline."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a local .env (gitignored) into the environment,
    without adding a dependency. Real env vars always win."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

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


@dataclass(frozen=True)
class CasePaths:
    """Where a run's artifacts are written. Synthetic → public (tracked);
    real → a gitignored directory so real PII never lands in the public repo."""
    case_record: Path
    changelog_md: Path
    petition: Path
    logs_dir: Path


# Synthetic / demo run → committed, public.
SYNTHETIC_PATHS = CasePaths(CASE_RECORD_PATH, CHANGELOG_MD_PATH, PETITION_PATH, LOGS_DIR)

# Real run → under /data/ (which is gitignored), so nothing is ever committed.
REAL_OUTPUT_DIR = DATA_DIR / "_run"
REAL_PATHS = CasePaths(
    REAL_OUTPUT_DIR / "case_record.json",
    REAL_OUTPUT_DIR / "changelog.md",
    REAL_OUTPUT_DIR / "petition_draft.md",
    REAL_OUTPUT_DIR / "logs",
)

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
    "Police Intimation": 0.88,
    "Discharge Summary": 0.85,
    "Interim Summary": 0.85,
    "Imaging Report": 0.83,
    "Disability Assessment Certificate": 0.95,
    "Hospital Bill": 0.90,
    "Salary Slip": 0.80,
    "CA Income Certificate": 0.85,
    "Form 16": 0.95,
    "ITR": 0.95,
    # AI vision interpretations of a scan/image — deliberately low so they are
    # always needs_human_review and never asserted as settled in the petition.
    "AI Vision Observation": 0.40,
}
DEFAULT_AUTHORITY = 0.85

# If two conflicting values differ in authority by at least this much, the
# higher one is treated as a CORRECTION. Otherwise it's a CONTRADICTION
# (parked for a human — never silently resolved).
CORRECTION_MARGIN = 0.10

# Stream ownership (the brief's mapping): liability facts come from police,
# income from financial, disability quantum from medical. A fact for an owned
# field extracted from a non-owning stream is ignored (and logged) — this stops
# e.g. a hospital note's vague "a lorry" from conflicting with the FIR's reg no.
# Fields NOT listed (victim_name, victim_age, accident_date, accident_place,
# injuries, image_finding, medical_expense_*) may legitimately appear in any
# stream — accident_date in particular is shared, which is how the cross-stream
# date contradiction is caught.
FIELD_STREAMS = {
    "offending_vehicle": {"police"},
    "offending_driver": {"police"},
    "vehicle_owner": {"police"},
    "insurer": {"police"},
    "policy_number": {"police"},
    "negligence": {"police"},
    "annual_income": {"financial"},
    "employment_type": {"financial"},
    "occupation": {"financial"},
    "functional_disability_pct": {"medical"},
    "permanent_disability": {"medical"},
    "hospitalization_days": {"medical"},
}

# Registration-/policy-like fields compared on their alphanumeric core, ignoring
# noise words, so "Lorry No. TN-19-K-4567" == "Lorry TN-19-K-4567".
ID_FIELDS = {"offending_vehicle", "policy_number"}
ID_NOISE_WORDS = {"no", "lorry", "truck", "vehicle", "bearing", "registration",
                  "reg", "car", "number", "bus", "auto"}

# Fields treated as numeric / date for value comparison.
NUMERIC_FIELDS = {"victim_age", "hospitalization_days", "functional_disability_pct", "annual_income"}
DATE_FIELDS = {"accident_date"}
# Name-like fields use initial-aware token matching (so "Ramesh K. Sharma"
# and "Ramesh Kumar Sharma" are the same fact, not a contradiction).
NAME_FIELDS = {"victim_name", "offending_driver", "vehicle_owner"}

# Narrative/descriptive fields: multiple sources can each contribute a phrasing
# without conflicting. Differing values are appended (corroboration), never
# flagged as contradictions, and are exempt from the single-active-fact rule.
NARRATIVE_FIELDS = {"injuries", "negligence", "accident_place", "permanent_disability",
                    "image_finding"}

NEEDS_REVIEW_BELOW = 0.80
