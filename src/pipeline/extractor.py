"""
Extract AssemblyStep objects from text chunks using LLM.
LLM is prompted to return JSON; output is parsed into AssemblyStep instances.
"""

import json
from typing import List

from pipeline.schema import AssemblyStep

SYSTEM_PROMPT = (
    "You are a precise technical procedure extractor. "
    "Extract assembly steps from the text and return ONLY a JSON array. "
    "No explanations, no markdown, no code fences, just the JSON array."
)

USER_PROMPT_TEMPLATE = """Extract all assembly/procedure steps from the technical text below.
Return a JSON array where each object has EXACTLY these keys:
"action", "component", "component_detail", "orientation", "applied_to",
"tool", "tool_detail", "assembly_detail", "confidence"

Rules:
- action: MUST be one of exactly three values: "Place", "Insert", "Screw in"
  - "Place"    → position a component onto something
  - "Insert"   → push/fit a component into a hole or slot
  - "Screw in" → rotate a threaded component to fasten it
- component: name of the part being acted on (e.g. "Screw 1", "Frame 2")
- component_detail: technical specs (e.g. "Diameter = 3mm; Length = 11mm;"), or ""
- orientation: positioning info if mentioned (e.g. "Hole 1 = Spacer 3;"), else ""
- applied_to: formatted as "X.Y;" where X is a component already present in the
  assembly (introduced in a previous step) and Y is a specific point on X (e.g. "Hole 1").
  Omit ".Y" if no specific point is mentioned (e.g. "Frame 1;").
  Special case: if X equals the current component itself, it means "place on workbench"
  (e.g. first step → "Frame 1;" where component is also Frame 1).
- tool: tool name if any, else ""
- tool_detail: tool specs if any, else ""
- assembly_detail: extra notes, else ""
- confidence: float 0.0-1.0, how certain you are this is a real procedure step
- If no procedure steps are found, return []

Text:
{text}

Output ONLY the JSON array:"""


def _parse_llm_json(raw: str) -> list:
    """Extract a JSON array from raw LLM output. Falls back to scanning for objects."""
    if not raw:
        return []

    start = raw.find('[')
    end = raw.rfind(']')
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw[start:end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Fallback: scan for individual JSON objects
    steps, depth, obj_start = [], 0, None
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    steps.append(json.loads(raw[obj_start:i + 1]))
                except json.JSONDecodeError:
                    pass
                obj_start = None
    return steps


def extract_from_chunk(chunk_text: str, llm, max_tokens: int = 1024) -> List[AssemblyStep]:
    """
    Call the LLM on a single text chunk, parse JSON output, return AssemblyStep list.
    Invalid/unparseable LLM responses produce an empty list (no crash).
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=chunk_text)},
    ]

    raw = llm.chat(messages=messages, max_tokens=max_tokens, temperature=0.1)
    raw_objects = _parse_llm_json(raw)

    steps = []
    for obj in raw_objects:
        if not isinstance(obj, dict):
            continue
        try:
            step = AssemblyStep(
                action=str(obj.get("action", "")).strip(),
                component=str(obj.get("component", "")).strip(),
                component_detail=str(obj.get("component_detail", "")).strip(),
                orientation=str(obj.get("orientation", "")).strip(),
                applied_to=str(obj.get("applied_to", "")).strip(),
                tool=str(obj.get("tool", "")).strip(),
                tool_detail=str(obj.get("tool_detail", "")).strip(),
                assembly_detail=str(obj.get("assembly_detail", "")).strip(),
                confidence=float(obj.get("confidence", 1.0)),
                evidence=chunk_text[:300],
            )
            steps.append(step)
        except Exception:
            # Silently skip malformed objects
            pass

    return steps
