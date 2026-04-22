"""
Main pipeline orchestrator.
PDF → parse → chunk → filter → extract → validate → refine → return steps
"""

import re
from pathlib import Path
from typing import List, Tuple

from document_processor.loader import DocumentLoader
from document_processor.chunker import TextChunker
from pipeline.extractor import extract_from_chunk
from pipeline.validator import validate_steps, dedup_steps
from pipeline.refiner import refine_steps
from pipeline.schema import AssemblyStep, ExtractionStats


def run_pipeline(file_path: str, llm, config: dict) -> Tuple[List[AssemblyStep], dict]:
    """
    Full extraction pipeline.

    Args:
        file_path: Absolute path to input document (PDF/DOCX/TXT).
        llm:       Loaded LanguageModel instance.
        config:    Pipeline config dict (from config.yaml).

    Returns:
        (steps, stats) where steps is the validated, indexed list of AssemblyStep.
    """
    max_tokens    = config.get('llm', {}).get('max_tokens', 1024)
    chunk_size    = config.get('chunking', {}).get('size', 1000)
    chunk_overlap = config.get('chunking', {}).get('overlap', 100)
    min_confidence = config.get('extraction', {}).get('min_confidence', 0.5)
    do_refine     = config.get('extraction', {}).get('refine_invalid', True)

    # 1. Load document
    doc = DocumentLoader.load(file_path)

    # 2. Chunk
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = chunker.split(doc.content, metadata=doc.metadata)

    # 3. Section filtering (heading + structural + keyword signals — see _looks_like_procedure)
    procedure_chunks = [c for c in chunks if _looks_like_procedure(c.text)]
    if not procedure_chunks:
        procedure_chunks = chunks   # fallback: process everything

    # 4. Extract raw steps via LLM
    raw_steps: List[AssemblyStep] = []
    total = len(procedure_chunks)
    for i, chunk in enumerate(procedure_chunks, 1):
        if not chunk.text.strip():
            continue
        print(f"  Extracting chunk {i}/{total} (doc chunk #{chunk.index})...")
        raw_steps.extend(extract_from_chunk(chunk.text, llm, max_tokens))

    # 5. Validate
    valid, invalid = validate_steps(raw_steps, min_confidence=min_confidence)

    # 6. Single refining pass on invalid steps
    num_refined = 0
    if do_refine and invalid:
        print(f"  Refining {len(invalid)} invalid steps...")
        refined_raw = refine_steps(invalid, llm, max_tokens)
        refined_valid, _ = validate_steps(refined_raw, min_confidence=min_confidence)
        valid.extend(refined_valid)
        valid = dedup_steps(valid)
        num_refined = len(refined_valid)

    # 7. Assign step indices
    for i, step in enumerate(valid, 1):
        step.step_index = i

    stats = ExtractionStats(
        num_chunks=len(chunks),
        num_chunks_processed=len(procedure_chunks),
        num_steps_raw=len(raw_steps),
        num_steps_invalid=len(invalid),
        num_steps_refined=num_refined,
        num_steps_valid=len(valid),
    ).model_dump()

    return valid, stats


def _looks_like_procedure(text: str) -> bool:
    """
    Multi-signal classifier: heading patterns + numbered-step structure + keyword density.
    A chunk is considered procedural if its total score reaches the threshold.

    Scoring:
      +3  a heading line explicitly names a procedural section
      +2  numbered/bulleted list with ≥2 items  (strong step-sequence signal)
      +2  ≥4 action keywords (dense procedural vocabulary)
      +1  2-3 action keywords (weak signal)

    Threshold: score ≥ 2  (same sensitivity as before, but far fewer false-negatives
    and much better recall on sections whose headings contain procedural language).
    """
    text_lower = text.lower()
    lines = text.splitlines()
    score = 0

    # ── Signal 1: procedural section heading ──────────────────────────────────
    # A "heading" is a short line (≤ 80 chars) or all-caps / title-case line.
    _HEADING_WORDS = re.compile(
        r'\b(?:assembl(?:y|ing)|install(?:ation|ing)|procedure|instructions?'
        r'|mounting|build(?:ing)?|setup|configuration|maintenance'
        r'|disassembl(?:y|ing)|integration|preparation|steps?'
        r'|how\s+to|quick\s+start|getting\s+started)\b'
    )
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        is_heading = (
            len(stripped) <= 80
            and (stripped.isupper() or stripped.istitle() or stripped.endswith(':'))
        )
        if is_heading and _HEADING_WORDS.search(stripped.lower()):
            score += 3
            break

    # ── Signal 2: numbered / bulleted list structure ──────────────────────────
    # Counts lines that start with "1.", "2)", "-", "*", "•", "Step N:"
    _LIST_ITEM = re.compile(r'^\s*(?:\d+[\.\)]|[-*•]|step\s*\d+\s*[:\.])\s+\w', re.IGNORECASE)
    list_items = sum(1 for ln in lines if _LIST_ITEM.match(ln))
    if list_items >= 2:
        score += 2

    # ── Signal 3: action-keyword density ─────────────────────────────────────
    _KEYWORDS = {
        'insert', 'screw', 'place', 'connect', 'tighten', 'attach',
        'install', 'mount', 'assemble', 'remove', 'disconnect',
        'step', 'procedure', 'warning', 'caution', 'tool', 'torque',
        'apply', 'fasten', 'align', 'secure', 'verify', 'solder',
        'bolt', 'nut', 'washer', 'bracket', 'cable', 'crimp',
    }
    kw_hits = sum(1 for kw in _KEYWORDS if kw in text_lower)
    if kw_hits >= 4:
        score += 2
    elif kw_hits >= 2:
        score += 1

    return score >= 2
