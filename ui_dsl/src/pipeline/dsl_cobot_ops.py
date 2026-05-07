"""
DSL parser and updater for cobot operations.

Both DSL formats are generated fresh from CSV — old format not supported.

External DSL per-step format:
    Step number: N
        Description: ...
        Involved Components: A, B, C
        Action: Place
        On: [[...], ...]
        Tool Type: Screwdriver_1 | null
        Cobot Operations:
            - pick_and_place(pick_pose=[...], ...)

Internal DSL per-step format (one line):
    Step(N).loadModel(N-1)
           .loadPart("Frame_1","Frame 1",{...})
           .anchor([...]).action("Place").on([[...]])
           .tool("Screwdriver_1","Screwdriver",{...})   OR  .tool(None,None)
           [.cobot(["op1(...)", ...])]
           .desc("...")
"""

import re
import json
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_call_args(s: str, method: str) -> str | None:
    """Return the raw content inside .method(...), handling nested brackets."""
    marker = f".{method}("
    idx = s.find(marker)
    if idx < 0:
        return None
    open_p = idx + len(marker) - 1
    depth = 0
    for j in range(open_p, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return s[open_p + 1 : j]
    return None


def _parse_two_json(s: str):
    """Parse 'json_val1, json_val2' → (val1, val2) using incremental decoding."""
    dec = json.JSONDecoder()
    v1, end1 = dec.raw_decode(s.strip())
    rest = s[end1:].lstrip().lstrip(",").lstrip()
    v2 = json.loads(rest)
    return v1, v2


def _parse_three_json(s: str):
    """Parse 'json_val1, json_val2, json_val3' → (val1, val2, val3)."""
    dec = json.JSONDecoder()
    v1, end1 = dec.raw_decode(s.strip())
    r1 = s[end1:].lstrip().lstrip(",").lstrip()
    v2, end2 = dec.raw_decode(r1)
    r2 = r1[end2:].lstrip().lstrip(",").lstrip()
    v3 = json.loads(r2)
    return v1, v2, v3


def _remove_cobot_call(s: str) -> str:
    """Remove .cobot([...]) from an internal DSL line."""
    idx = s.find(".cobot(")
    if idx < 0:
        return s
    start = idx + len(".cobot(") - 1
    depth = 0
    for j in range(start, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return s[:idx] + s[j + 1 :]
    return s


# ── External DSL parser ───────────────────────────────────────────────────────

def parse_external_dsl(filepath: str) -> dict:
    """
    Parse external DSL file.

    Returns:
        {
            "project_name": str,
            "steps": [{
                "step_number": int,
                "description": str,
                "involved_components": [str, ...],
                "action": str,
                "on": list,
                "tool_type": str | None,
                "cobot_operations": [str, ...]
            }, ...]
        }
    """
    result: dict = {"project_name": "", "steps": []}

    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        if line.rstrip("\n").startswith("Project:"):
            result["project_name"] = line.rstrip("\n").split(":", 1)[1].strip()
            break

    in_steps = False
    cur: dict | None = None
    in_cobot = False

    for line in lines:
        s = line.rstrip("\n")

        # ── Section boundaries ─────────────────────────────────────────────
        if s == "\tAssembly Steps:":
            in_steps = True
            continue

        if not in_steps:
            continue

        # Leaving Assembly Steps (another top-level tab section)
        if s.startswith("\t") and not s.startswith("\t\t") and s.strip():
            if cur is not None:
                result["steps"].append(cur)
                cur = None
            in_steps = False
            in_cobot = False
            continue

        # ── Step number ────────────────────────────────────────────────────
        if s.startswith("\t\tStep number:"):
            if cur is not None:
                result["steps"].append(cur)
            try:
                n = int(s.split(":", 1)[1].strip())
            except ValueError:
                n = -1
            cur = {
                "step_number": n,
                "description": "",
                "involved_components": [],
                "action": "",
                "on": [],
                "tool_type": None,
                "cobot_operations": [],
            }
            in_cobot = False
            continue

        if cur is None:
            continue

        # ── Step-level fields ──────────────────────────────────────────────
        if s.startswith("\t\t\tDescription:"):
            cur["description"] = s.split(":", 1)[1].strip()
            in_cobot = False
        elif s.startswith("\t\t\tInvolved Components:"):
            comps = s.split(":", 1)[1].strip()
            cur["involved_components"] = [c.strip() for c in comps.split(",")]
            in_cobot = False
        elif s.startswith("\t\t\tAction:"):
            cur["action"] = s.split(":", 1)[1].strip()
            in_cobot = False
        elif s.startswith("\t\t\tOn:"):
            val = s.split(":", 1)[1].strip()
            try:
                cur["on"] = json.loads(val)
            except json.JSONDecodeError:
                cur["on"] = []
            in_cobot = False
        elif s.startswith("\t\t\tTool Type:"):
            val = s.split(":", 1)[1].strip()
            cur["tool_type"] = None if val == "null" else val
            in_cobot = False
        elif s == "\t\t\tCobot Operations:":
            in_cobot = True

        # ── Cobot Operations items ─────────────────────────────────────────
        elif in_cobot and s.startswith("\t\t\t\t- "):
            cur["cobot_operations"].append(s[5:].strip())

    if cur is not None:
        result["steps"].append(cur)

    return result


# ── External DSL updater ──────────────────────────────────────────────────────

def update_external_dsl_cobot_ops(filepath: str, step_ops: dict) -> None:
    """
    Update cobot operations in external DSL.

    step_ops: {step_num (int): [op_string, ...]}
    - Present key with non-empty list → write those ops after Tool Type line
    - Present key with empty list → remove Cobot Operations block
    - Absent key → leave unchanged
    """
    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    output = []
    i = 0
    cur_step: int | None = None
    ops_written = False

    while i < len(lines):
        line = lines[i]
        s = line.rstrip("\n")

        # ── Step number ────────────────────────────────────────────────────
        if s.startswith("\t\tStep number:"):
            try:
                cur_step = int(s.split(":", 1)[1].strip())
            except ValueError:
                cur_step = None
            ops_written = False
            output.append(line)
            i += 1
            continue

        # ── After Tool Type → write new cobot ops ─────────────────────────
        if s.startswith("\t\t\tTool Type:") and cur_step is not None and not ops_written:
            output.append(line)
            i += 1
            if cur_step in step_ops:
                ops = step_ops[cur_step]
                if ops:
                    output.append("\t\t\tCobot Operations:\n")
                    for op in ops:
                        output.append(f"\t\t\t\t- {op}\n")
            ops_written = True
            continue

        # ── Existing Cobot Operations block → skip (already wrote new ones) ─
        if s == "\t\t\tCobot Operations:":
            i += 1
            while i < len(lines) and lines[i].rstrip("\n").startswith("\t\t\t\t"):
                i += 1
            continue

        output.append(line)
        i += 1

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(output)


# ── Internal DSL updater ──────────────────────────────────────────────────────

def update_internal_dsl_cobot_ops(filepath: str, step_ops: dict) -> None:
    """
    Update .cobot([...]) calls in internal DSL (new 3-arg loadPart/tool format).

    step_ops: {step_num (int): [op_string, ...]}
    """
    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    output = []
    for line in lines:
        s = line.rstrip("\n")
        if not s.startswith("Step("):
            output.append(line)
            continue
        m = re.match(r"Step\((\d+)\)", s)
        if not m:
            output.append(line)
            continue
        step_num = int(m.group(1))
        s = _remove_cobot_call(s)
        if step_num in step_ops and step_ops[step_num]:
            cobot_part = ".cobot(" + json.dumps(step_ops[step_num]) + ")"
            s = s.replace(".desc(", cobot_part + ".desc(", 1)
        output.append(s + "\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(output)
