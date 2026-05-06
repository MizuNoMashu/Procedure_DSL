"""
Intermediate schema for extracted assembly steps.
LLM output → AssemblyStep → validation → CSV
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class AssemblyStep(BaseModel):
    step_index: int = 0
    source_chunk_index: int = 0        # index of the chunk (or batch start) in the document
    source_page: Optional[int] = None  # 1-based page number (PDF only; None for DOCX/TXT)
    action: str = ""
    component: str = ""
    component_detail: str = ""
    orientation: str = ""
    applied_to: str = ""
    tool: str = ""
    tool_detail: str = ""
    assembly_detail: str = ""
    warnings: List[str] = []
    evidence: str = ""        # truncated preview of source text (first 300 chars)
    source_text: str = ""     # full chunk/batch text used for extraction and refining
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractionStats(BaseModel):
    num_chunks: int = 0
    num_chunks_processed: int = 0
    num_steps_raw: int = 0
    num_steps_invalid: int = 0
    num_steps_refined: int = 0
    num_steps_valid: int = 0
