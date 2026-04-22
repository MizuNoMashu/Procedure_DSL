"""
Single-pass refining loop: re-extract invalid steps using targeted error-context prompts.
Each step is re-prompted with its specific validation failures so the LLM knows exactly
what to fix rather than repeating the same generic extraction.
"""

from typing import List
from pipeline.schema import AssemblyStep
from pipeline.extractor import refine_step_with_context


def refine_steps(
    invalid_steps: List[AssemblyStep],
    llm,
    max_tokens: int = 512,
) -> List[AssemblyStep]:
    """
    For each invalid step that has evidence text, re-run extraction with a
    targeted prompt that includes the previous (wrong) extraction and the
    specific validation warnings to guide the correction.

    Returns newly extracted steps (not yet validated — caller should validate).
    """
    refined = []
    seen_evidence: set = set()

    for step in invalid_steps:
        evidence = step.evidence.strip()
        if not evidence or evidence in seen_evidence:
            continue
        seen_evidence.add(evidence)

        new_steps = refine_step_with_context(step, llm, max_tokens)
        refined.extend(new_steps)

    return refined
