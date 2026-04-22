"""
Extract AssemblyStep objects from text chunks using LLM.
LLM is prompted to return JSON; output is parsed into AssemblyStep instances.
"""

import json
from typing import List

from pipeline.schema import AssemblyStep

SYSTEM_PROMPT = (
    "You are a faithful technical procedure extractor. "
    "Extract assembly steps from the text and return ONLY a JSON array. "
    "No explanations, no markdown, no code fences, just the JSON array. "
    "CRITICAL: Never invent, infer, or guess field values. "
    "If information is not explicitly stated in the text, use empty string \"\"."
)

USER_PROMPT_TEMPLATE = """Extract all assembly/procedure steps from the technical text below.
Return a JSON array where each object has EXACTLY these keys:
"action", "component", "component_detail", "orientation", "applied_to",
"tool", "tool_detail", "assembly_detail", "confidence"

=== ABSOLUTE RULE: DO NOT INVENT ===
Every field must come DIRECTLY and VERBATIM from the text.
If something is NOT explicitly written in the text → use empty string "".
Never infer, guess, or add information not present in the source text.

=== FIELD RULES ===
- action: MUST be one of exactly three values: "Place", "Insert", "Screw in"
  Map document verbs as follows:
  - "Place"    → place, lay, set, mount, position, put
  - "Insert"   → insert, attach, connect, install, fit, slide, push into
  - "Screw in" → screw, fasten, solder, tighten, bolt
  Never skip a step because its verb is unusual. Always pick the closest action.
  If truly ambiguous, default to "Place".
- component: name of the part being acted on, copied verbatim from text
- component_detail: ONLY if the text explicitly gives technical specs (dimensions,
  materials, part numbers). If NOT stated → ""
- orientation: ONLY if the text EXPLICITLY describes a positional or spatial
  relationship for this step (e.g. "Rail 2 = Board", "Ensure proper orientation!").
  Copy the exact words from the text. If orientation is NOT mentioned → ""
  DO NOT INVENT orientation values.
- applied_to: the target component(s) where the action is performed, as found in text.
  Format: "ComponentName;" or "ComponentA; ComponentB;" if multiple.
  If not stated → ""
- tool: tool name ONLY if explicitly mentioned in text, else ""
- tool_detail: tool specifications ONLY if explicitly stated, else ""
- assembly_detail: any additional notes, warnings, or instructions present in the text.
  Copy verbatim. If nothing extra → ""
- confidence: float 0.0-1.0, your certainty that this is a real procedure step

=== COVERAGE ===
Extract EVERY step present in the text. Do not skip steps.
If the text has 10 steps, return 10 objects.
If no procedure steps are found, return [].

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
