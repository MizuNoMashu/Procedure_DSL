"""
Single-pass refining loop: re-extract from evidence of invalid steps.
TODO: add smarter re-prompting that includes the validation error context.
"""

from typing import List
from pipeline.schema import AssemblyStep
from pipeline.extractor import extract_from_chunk


def refine_steps(
    invalid_steps: List[AssemblyStep],
    llm,
    max_tokens: int = 1024,
) -> List[AssemblyStep]:
    """
    For each invalid step that has evidence text, re-run extraction.
    Returns newly extracted steps (not yet validated — caller should validate).
    """
    refined = []
    seen_evidence: set = set()

    for step in invalid_steps:
        evidence = step.evidence.strip()
        if not evidence or evidence in seen_evidence:
            continue
        seen_evidence.add(evidence)

        # TODO: build a more targeted prompt using step.warnings to guide the LLM
        new_steps = extract_from_chunk(evidence, llm, max_tokens)
        refined.extend(new_steps)

    return refined
