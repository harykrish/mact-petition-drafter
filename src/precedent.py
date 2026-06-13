"""Deterministic MACT compensation arithmetic, grounded in Sarla Verma (2009)
and Pranay Sethi (2017). This is what the petition verifier re-derives from
scratch — independently of the drafter — to check M6, M7, M8.

Pure functions, no LLM. See /precedent/*.md for the legal notes.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def sarla_verma_multiplier(age: int) -> Tuple[int, str]:
    """Return (multiplier, band-label) for the victim's age (Sarla Verma table)."""
    if age <= 15:
        return 15, "up to 15"
    if age <= 25:
        return 18, "15-25"
    if age <= 30:
        return 17, "26-30"
    if age <= 35:
        return 16, "31-35"
    if age <= 40:
        return 15, "36-40"
    if age <= 45:
        return 14, "41-45"
    if age <= 50:
        return 13, "46-50"
    if age <= 55:
        return 11, "51-55"
    if age <= 60:
        return 9, "56-60"
    if age <= 65:
        return 7, "61-65"
    if age <= 70:
        return 5, "66-70"
    return 5, "over 70"


def pranay_sethi_future_prospects(age: int, employment_type: str) -> Tuple[float, str]:
    """Return (fraction, rationale) for the future-prospects addition.

    employment_type: 'salaried_permanent' uses the salaried table;
    'self_employed' / 'fixed_wage' use the lower table.
    """
    salaried = employment_type == "salaried_permanent"
    if age < 40:
        frac = 0.50 if salaried else 0.40
        band = "18-40"
    elif age < 50:
        frac = 0.30 if salaried else 0.25
        band = "40-50"
    elif age < 60:
        frac = 0.15 if salaried else 0.10
        band = "50-60"
    else:
        frac = 0.0
        band = "over 60"
    kind = "salaried/permanent" if salaried else "self-employed/fixed-wage"
    return frac, "%s, age band %s -> +%d%%" % (kind, band, round(frac * 100))


def loss_of_future_earning(annual_income: int, age: int, employment_type: str,
                           functional_disability_pct: int) -> Dict[str, object]:
    """Injury-claim formula:
        annual_income * (1 + future_prospects) * multiplier * disability%
    Returns the figure plus every intermediate term for transparent grading.
    """
    multiplier, m_band = sarla_verma_multiplier(age)
    fp, fp_note = pranay_sethi_future_prospects(age, employment_type)
    enhanced = annual_income * (1 + fp)
    total = enhanced * multiplier * (functional_disability_pct / 100.0)
    amount = int(round(total))
    return {
        "annual_income": annual_income,
        "future_prospects_fraction": fp,
        "future_prospects_note": fp_note,
        "multiplier": multiplier,
        "multiplier_band": m_band,
        "functional_disability_pct": functional_disability_pct,
        "enhanced_annual_income": int(round(enhanced)),
        "amount": amount,
        "formula": "%d x (1+%.2f) x %d x %d%% = %d" % (
            annual_income, fp, multiplier, functional_disability_pct, amount),
    }


def medical_expenses_total(items: List[Tuple[str, int]]) -> Dict[str, object]:
    """Sum itemised medical-expense facts. items = [(label, amount), ...]."""
    total = sum(a for _, a in items)
    return {
        "items": [{"label": l, "amount": a} for l, a in items],
        "amount": int(total),
        "formula": " + ".join(str(a) for _, a in items) + " = %d" % int(total) if items else "0",
    }
