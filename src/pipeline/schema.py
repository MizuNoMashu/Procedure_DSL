"""
Intermediate schema for extracted assembly steps.
LLM output → AssemblyStep → validation → CSV
"""

from pydantic import BaseModel, Field
from typing import List


class AssemblyStep(BaseModel):
    step_index: int = 0
    action: str = ""
    component: str = ""
    component_detail: str = ""
    orientation: str = ""
    applied_to: str = ""
    tool: str = ""
    tool_detail: str = ""
    assembly_detail: str = ""
    warnings: List[str] = []
    evidence: str = ""   # raw chunk text that produced this step (first 300 chars)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractionStats(BaseModel):
    num_chunks: int = 0
    num_chunks_processed: int = 0
    num_steps_raw: int = 0
    num_steps_invalid: int = 0
    num_steps_refined: int = 0
    num_steps_valid: int = 0
