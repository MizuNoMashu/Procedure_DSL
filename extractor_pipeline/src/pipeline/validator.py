"""
Validate and deduplicate AssemblyStep objects.
Returns (valid_steps, invalid_steps).
"""

from typing import List, Tuple
from pipeline.schema import AssemblyStep

ALLOWED_ACTIONS = {"Place", "Insert", "Screw in", "Connect", "Solder", "Apply", "Remove"}


def validate_steps(
    steps: List[AssemblyStep],
    min_confidence: float = 0.5,
) -> Tuple[List[AssemblyStep], List[AssemblyStep]]:
    """
    Split steps into valid/invalid based on required fields and confidence.
    Deduplicates valid steps before returning.
    """
    valid, invalid = [], []

    for step in steps:
        issues = _check(step, min_confidence)
        if issues:
            step.warnings = issues
            invalid.append(step)
        else:
            valid.append(step)
    return valid, invalid
    # return dedup_steps(valid), invalid


def dedup_steps(steps: List[AssemblyStep]) -> List[AssemblyStep]:
    """Remove duplicate steps (same action + component + applied_to)."""
    seen: set = set()
    unique = []
    for step in steps:
        key = (
            step.action.strip().lower(),
            step.component.strip().lower(),
            step.applied_to.strip().lower(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(step)
    return unique


def compute_hybrid_confidence(step: AssemblyStep) -> float:
    """
    Hybrid confidence score: 40% LLM self-report + 60% field completeness.

    Field score weights (sum to 1.0):
      action  valid  → 0.35
      component       → 0.35
      applied_to      → 0.20
      tool            → 0.10

    Result is clamped to [0.0, 1.0] and rounded to 3 decimal places.
    """
    field_score = 0.0
    if step.action.strip() in ALLOWED_ACTIONS:
        field_score += 0.35
    if step.component.strip():
        field_score += 0.35
    if step.applied_to.strip():
        field_score += 0.20
    if step.tool.strip():
        field_score += 0.10
    hybrid = 0.4 * step.confidence + 0.6 * field_score
    return round(min(max(hybrid, 0.0), 1.0), 3)


def _check(step: AssemblyStep, min_confidence: float) -> List[str]:
    issues = []
    action = step.action.strip()
    if not action:
        issues.append("missing action")
    elif action not in ALLOWED_ACTIONS:
        issues.append(f"invalid action '{action}' (allowed: {sorted(ALLOWED_ACTIONS)})")
    if not step.component.strip():
        issues.append("missing component")
    if step.confidence < min_confidence:
        issues.append(f"low confidence ({step.confidence:.2f} < {min_confidence})")
    return issues
