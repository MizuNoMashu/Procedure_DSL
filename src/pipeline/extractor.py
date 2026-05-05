"""
Extract AssemblyStep objects from text chunks using LLM.
LLM is prompted to return JSON; output is parsed into AssemblyStep instances.
"""

import json
from typing import List, Optional
from pathlib import Path

from pipeline.schema import AssemblyStep

# JSON schema passed to lm-format-enforcer for constrained decoding.
# If the library is not installed the schema is ignored and normal parsing is used.
_STEPS_ARRAY_SCHEMA = json.dumps({
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "action":           {"type": "string"},
            "component":        {"type": "string"},
            "component_detail": {"type": "string"},
            "orientation":      {"type": "string"},
            "applied_to":       {"type": "string"},
            "tool":             {"type": "string"},
            "tool_detail":      {"type": "string"},
            "assembly_detail":  {"type": "string"},
            "confidence":       {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": [
            "action", "component", "component_detail", "orientation",
            "applied_to", "tool", "tool_detail", "assembly_detail", "confidence",
        ],
    },
})

SYSTEM_PROMPT = (
    "You are a faithful technical procedure extractor. "
    "Extract assembly steps from the text and return ONLY a JSON array. "
    "No explanations, no markdown, no code fences, just the JSON array. "
    "CRITICAL: Never invent, infer, or guess field values. "
    "If information is not explicitly stated in the text, use empty string \"\"."
)


def _load_few_shot_examples() -> str:
    """Load few-shot examples from JSON file and format them as a prompt section."""
    examples_path = Path(__file__).parent.parent / "examples" / "few_shot_examples.json"

    if not examples_path.exists():
        return ""

    try:
        with open(examples_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        examples_text = "\n=== EXAMPLES OF CORRECT EXTRACTION ===\n"
        for i, example in enumerate(data.get("examples", []), 1):
            input_text = example.get("input_text", "")
            output_json = json.dumps(example.get("output", []), indent=2)
            examples_text += f"\nExample {i}:\nInput text: {input_text}\nOutput JSON:\n{output_json}\n"

        examples_text += "\n=== NOW EXTRACT FROM THE ACTUAL TEXT ===\n"
        return examples_text
    except Exception:
        return ""  # Silently fail if examples can't be loaded


FEW_SHOT_EXAMPLES = _load_few_shot_examples()

USER_PROMPT_TEMPLATE = """Extract all assembly/procedure steps from the technical text below.
Return a JSON array where each object has EXACTLY these keys:
"action", "component", "component_detail", "orientation", "applied_to",
"tool", "tool_detail", "assembly_detail", "confidence"
{few_shot_examples}
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


REFINE_PROMPT_TEMPLATE = """You previously extracted an assembly step from the text below, but it failed validation.
Re-read the SAME text and return a corrected JSON array, fixing ONLY the listed errors.

=== ORIGINAL TEXT ===
{text}

=== YOUR PREVIOUS (INVALID) EXTRACTION ===
{previous_json}

=== VALIDATION ERRORS TO FIX ===
{errors}

=== CORRECTION RULES ===
- action: MUST be exactly one of "Place", "Insert", "Screw in"
  Map verbs → Place (place/lay/set/mount/put), Insert (insert/attach/connect/install/fit/push), Screw in (screw/fasten/solder/tighten/bolt)
  If the action was wrong, pick the closest valid one. Never leave it empty or use a different value.
- component: the part being acted on (REQUIRED — cannot be empty or "not specified").
  If the text does not name a part, use the most specific noun you can find.
- All other fields: copy verbatim from text or use "" if truly not stated.
- confidence: float 0.0–1.0, your certainty this is a real assembly step.

Return ONLY a JSON array (no markdown, no explanation):"""


def _build_steps_from_objects(
    raw_objects: list,
    source_text: str,
    chunk_index: int = 0,
    source_page: Optional[int] = None,
) -> List[AssemblyStep]:
    """Shared helper: convert a list of parsed dicts into AssemblyStep objects."""
    steps = []
    for obj in raw_objects:
        if not isinstance(obj, dict):
            continue
        try:
            steps.append(AssemblyStep(
                action=str(obj.get("action", "")).strip(),
                component=str(obj.get("component", "")).strip(),
                component_detail=str(obj.get("component_detail", "")).strip(),
                orientation=str(obj.get("orientation", "")).strip(),
                applied_to=str(obj.get("applied_to", "")).strip(),
                tool=str(obj.get("tool", "")).strip(),
                tool_detail=str(obj.get("tool_detail", "")).strip(),
                assembly_detail=str(obj.get("assembly_detail", "")).strip(),
                confidence=float(obj.get("confidence", 1.0)),
                evidence=source_text[:300],
                source_text=source_text,
                source_chunk_index=chunk_index,
                source_page=source_page,
            ))
        except Exception:
            pass
    return steps


def refine_step_with_context(step: AssemblyStep, llm, max_tokens: int = 512) -> List[AssemblyStep]:
    """
    Re-extract a single invalid step using a targeted prompt that includes
    the previous extraction and the specific validation errors.
    Uses full source_text so the LLM has the complete original context.
    """
    prev = {
        "action": step.action,
        "component": step.component,
        "component_detail": step.component_detail,
        "orientation": step.orientation,
        "applied_to": step.applied_to,
        "tool": step.tool,
        "tool_detail": step.tool_detail,
        "assembly_detail": step.assembly_detail,
        "confidence": step.confidence,
    }
    errors_text = "\n".join(f"- {w}" for w in step.warnings) if step.warnings else "- Unknown validation error"
    source = step.source_text or step.evidence or "(no source text available)"

    prompt = REFINE_PROMPT_TEMPLATE.format(
        text=source,
        previous_json=json.dumps(prev, indent=2),
        errors=errors_text,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    raw = llm.chat(messages=messages, max_tokens=max_tokens, temperature=0.0,
                   json_schema=_STEPS_ARRAY_SCHEMA)
    return _build_steps_from_objects(_parse_llm_json(raw), source,
                                     step.source_chunk_index, step.source_page)


def extract_from_chunk(
    chunk_text: str,
    llm,
    max_tokens: int = 1024,
    chunk_index: int = 0,
    source_page: Optional[int] = None,
) -> List[AssemblyStep]:
    """
    Call the LLM on a single text chunk (or batched text), parse JSON output,
    return AssemblyStep list. Invalid/unparseable LLM responses produce an empty list.
    chunk_index and source_page are stored on each step to preserve document provenance.
    On empty/unparseable output, retries once at temperature=0.0 before giving up.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
            few_shot_examples=FEW_SHOT_EXAMPLES,
            text=chunk_text
        )},
    ]

    raw = llm.chat(messages=messages, max_tokens=max_tokens, temperature=0.1,
                   json_schema=_STEPS_ARRAY_SCHEMA)
    steps = _build_steps_from_objects(_parse_llm_json(raw), chunk_text, chunk_index, source_page)

    # Retry once at temperature=0 if the output was empty or unparseable
    if not steps:
        raw = llm.chat(messages=messages, max_tokens=max_tokens, temperature=0.0,
                       json_schema=_STEPS_ARRAY_SCHEMA)
        steps = _build_steps_from_objects(_parse_llm_json(raw), chunk_text, chunk_index, source_page)

    return steps
