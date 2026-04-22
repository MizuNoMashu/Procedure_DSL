"""
Validate and deduplicate AssemblyStep objects.
Returns (valid_steps, invalid_steps).
"""

from typing import List, Tuple
from pipeline.schema import AssemblyStep

ALLOWED_ACTIONS = {"Place", "Insert", "Screw in"}


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

    return dedup_steps(valid), invalid


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
