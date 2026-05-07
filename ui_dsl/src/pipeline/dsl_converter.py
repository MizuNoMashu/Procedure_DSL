"""
Bidirectional DSL converter.

Internal → External:  fully lossless (new 3-arg loadPart/tool format contains all data).
External → Internal:  fully lossless (new XR Simulation block contains all missing structured data).

Both conversions require the new DSL format generated after the generator updates.
"""

import re
import json
from pathlib import Path

from pipeline.dsl_cobot_ops import (
    parse_external_dsl,
    _extract_call_args,
    _parse_two_json,
    _parse_three_json,
    _remove_cobot_call,
)


# ── Internal DSL parser ───────────────────────────────────────────────────────

def parse_internal_dsl(filepath: str) -> dict:
    """
    Parse internal DSL (new format) into structured data.

    Returns:
        {
            "project_name": str,
            "steps": [{
                "step_number": int,
                "prev_model": int,
                "comp_type": str,       # e.g. "Frame_1"
                "comp_name": str,       # e.g. "Frame 1"
                "comp_detail": dict,
                "anchor": list,
                "action": str,
                "on": list,
                "tool_type": str | None,
                "tool_name": str | None,
                "tool_detail": dict,
                "cobot_ops": [str, ...],
                "description": str,
            }, ...]
        }
    """
    path = Path(filepath)
    # Derive project name from filename: Cubesat_internal_DSL.txt → Cubesat
    project_name = re.sub(r"_internal_DSL$", "", path.stem)

    steps = []
    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        s = line.strip()
        if not s.startswith("Step("):
            continue

        m = re.match(r"Step\((\d+)\)", s)
        if not m:
            continue
        step_num = int(m.group(1))

        # loadModel(N-1)
        lm_raw = _extract_call_args(s, "loadModel")
        prev_model = int(lm_raw) if lm_raw is not None else step_num - 1

        # loadPart("CompType", "CompName", {specs})
        lp_raw = _extract_call_args(s, "loadPart")
        if lp_raw:
            comp_type, comp_name, comp_detail = _parse_three_json(lp_raw)
        else:
            comp_type = comp_name = ""
            comp_detail = {}

        # anchor([...])
        anchor_raw = _extract_call_args(s, "anchor")
        anchor = json.loads(anchor_raw) if anchor_raw is not None else []

        # action("verb")
        action_raw = _extract_call_args(s, "action")
        action = json.loads(action_raw) if action_raw is not None else ""

        # on([[...], ...])
        on_raw = _extract_call_args(s, "on")
        on = json.loads(on_raw) if on_raw is not None else []

        # tool("ToolType","ToolInst",{specs})  OR  tool(None,None)
        tool_raw = _extract_call_args(s, "tool")
        if tool_raw and not tool_raw.startswith("None"):
            tool_type, tool_name, tool_detail = _parse_three_json(tool_raw)
        else:
            tool_type = tool_name = None
            tool_detail = {}

        # cobot([...])  – optional
        cobot_raw = _extract_call_args(s, "cobot")
        cobot_ops = json.loads(cobot_raw) if cobot_raw else []

        # desc("...")
        desc_raw = _extract_call_args(s, "desc")
        description = json.loads(desc_raw) if desc_raw is not None else ""

        steps.append(
            {
                "step_number": step_num,
                "prev_model": prev_model,
                "comp_type": comp_type,
                "comp_name": comp_name,
                "comp_detail": comp_detail,
                "anchor": anchor,
                "action": action,
                "on": on,
                "tool_type": tool_type,
                "tool_name": tool_name,
                "tool_detail": tool_detail,
                "cobot_ops": cobot_ops,
                "description": description,
            }
        )

    return {"project_name": project_name, "steps": steps}


# ── Resource grouper (used by internal → external) ────────────────────────────

def _group_resources(steps: list) -> dict:
    """
    Group component and tool instances by matching specs.

    Returns: {general_name: [{"specs": dict, "instances": [str], "quantity": int}]}

    'quantity' = total usage count (increments per step even if instance name repeats).
    'instances' = unique instance names seen.
    """
    resources: dict = {}

    for step in steps:
        pairs = [(step["comp_type"], step["comp_name"], step["comp_detail"])]
        if step["tool_type"]:
            pairs.append((step["tool_type"], step["tool_name"], step["tool_detail"]))

        for gen_type, inst_name, detail in pairs:
            if not gen_type or not inst_name:
                continue
            detail = detail or {}

            # General name = type without trailing _N suffix
            general = re.sub(r"_\d+$", "", gen_type)

            if general not in resources:
                resources[general] = []

            # Comparison key: exclude empty-list values (structural placeholders)
            cmp = {k: v for k, v in detail.items() if v != []}

            found = None
            for grp in resources[general]:
                if {k: v for k, v in grp["specs"].items() if v != []} == cmp:
                    found = grp
                    break

            if found is None:
                resources[general].append(
                    {"specs": dict(detail), "instances": [inst_name], "quantity": 1}
                )
            else:
                found["quantity"] += 1
                if inst_name not in found["instances"]:
                    found["instances"].append(inst_name)

    return resources


def _fmt_val(v) -> str:
    """Format a value for the external DSL (no JSON quotes for plain strings)."""
    if isinstance(v, str):
        return v
    if isinstance(v, list) and not v:
        return "[]"
    return json.dumps(v)


# ── Internal → External ───────────────────────────────────────────────────────

def internal_to_external(int_filepath: str, output_path: str) -> str:
    """
    Convert internal DSL to external DSL.
    Returns the path of the generated file.
    """
    data = parse_internal_dsl(int_filepath)
    project_name = data["project_name"]
    steps = data["steps"]
    resources = _group_resources(steps)

    lines = [f"Project: {project_name}\n"]

    # ── Resources Needed ──────────────────────────────────────────────────
    lines.append("\tResources Needed:\n")
    for general, groups in resources.items():
        for i, grp in enumerate(groups, 1):
            type_name = f"{general}_{i}"
            lines.append(f"\t\tGeneral Type Name: {type_name}\n")
            lines.append(f"\t\t\tQuantity: {grp['quantity']}\n")
            lines.append(f"\t\t\tInstances:\n")
            for inst in grp["instances"]:
                lines.append(f"\t\t\t\t- {inst}\n")

    # ── Assembly Steps ────────────────────────────────────────────────────
    lines.append("\tAssembly Steps:\n")
    for step in steps:
        on_comps = [t[0] for t in step["on"]]
        involved = [step["comp_name"]] + on_comps
        involved_str = ", ".join(involved)
        tool_type_str = step["tool_type"] if step["tool_type"] else "null"

        lines.append(f"\t\tStep number: {step['step_number']}\n")
        lines.append(f"\t\t\tDescription: {step['description']}\n")
        lines.append(f"\t\t\tInvolved Components: {involved_str}\n")
        lines.append(f"\t\t\tAction: {step['action']}\n")
        lines.append(f"\t\t\tOn: {json.dumps(step['on'])}\n")
        lines.append(f"\t\t\tTool Type: {tool_type_str}\n")
        if step["cobot_ops"]:
            lines.append(f"\t\t\tCobot Operations:\n")
            for op in step["cobot_ops"]:
                lines.append(f"\t\t\t\t- {op}\n")

    # ── Resources Infos ───────────────────────────────────────────────────
    lines.append("\tResources Infos:\n")
    for general, groups in resources.items():
        for i, grp in enumerate(groups, 1):
            type_name = f"{general}_{i}"
            lines.append(f"\t\tGeneral Type Name: {type_name}\n")
            for k, v in grp["specs"].items():
                lines.append(f"\t\t\t{k}: {_fmt_val(v)}\n")
            lines.append(f"\t\t\tQuantity: {grp['quantity']}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return output_path


# ── External → Internal ───────────────────────────────────────────────────────

def external_to_internal(ext_filepath: str, output_path: str) -> str:
    """
    Convert external DSL to internal DSL.
    Tool instance and detail are inferred from the Resources sections
    (instances of the same type are interchangeable — same specs).
    Anchor is set to [] and will be filled in by the XR editor.
    Returns the path of the generated file.
    """
    data = parse_external_dsl(ext_filepath)
    project_name = data["project_name"]
    steps = data["steps"]

    inst_map = _build_instance_map(ext_filepath)
    type_map = _build_type_map(ext_filepath)

    lines = []
    for step in steps:
        step_num = step["step_number"]
        prev_model = step_num - 1

        # Component
        comp_name = (step["involved_components"] or [""])[0]
        comp_entry = inst_map.get(comp_name, {"type": _infer_type(comp_name), "specs": {}})
        comp_type   = comp_entry["type"]
        comp_detail = comp_entry["specs"]

        action = step["action"]
        on     = step["on"]
        anchor = []   # XR-specific; will be assigned by the XR editor

        # Tool — infer instance and detail from Resources sections
        tool_type_str = step["tool_type"]
        if tool_type_str and tool_type_str != "null":
            entry = type_map.get(tool_type_str, {})
            tool_inst   = entry.get("instance", tool_type_str)
            tool_detail = entry.get("specs", {})
            tool_part   = f'.tool("{tool_type_str}","{tool_inst}",{json.dumps(tool_detail)})'
        else:
            tool_part = ".tool(None,None)"

        cobot_ops = step["cobot_operations"]
        desc = step["description"].replace('"', '\\"')

        line = (
            f"Step({step_num})"
            f".loadModel({prev_model})"
            f'.loadPart("{comp_type}","{comp_name}",{json.dumps(comp_detail)})'
            f".anchor({json.dumps(anchor)})"
            f'.action("{action}")'
            f".on({json.dumps(on)})"
            + tool_part
        )
        if cobot_ops:
            line += ".cobot(" + json.dumps(cobot_ops) + ")"
        line += f'.desc("{desc}")'

        lines.append(line + "\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return output_path


def _build_instance_map(ext_filepath: str) -> dict:
    """
    Parse Resources Needed + Resources Infos sections of the external DSL
    to build a map:  instance_name → {"type": "Frame_1", "specs": {...}}
    """
    with open(ext_filepath, encoding="utf-8") as f:
        lines = f.readlines()

    # First pass: Resources Infos → type_name → specs
    type_specs: dict = {}
    in_infos = False
    cur_type = None

    for line in lines:
        s = line.rstrip("\n")
        if s == "\tResources Infos:":
            in_infos = True
            continue
        if not in_infos:
            continue
        if s.startswith("\t") and not s.startswith("\t\t") and s.strip():
            break  # left the section
        if s.startswith("\t\tGeneral Type Name:"):
            cur_type = s.split(":", 1)[1].strip()
            type_specs[cur_type] = {}
        elif cur_type and s.startswith("\t\t\t") and ":" in s:
            kv = s.strip().split(":", 1)
            k, v = kv[0].strip(), kv[1].strip()
            if k == "Quantity":
                continue
            try:
                type_specs[cur_type][k] = json.loads(v)
            except json.JSONDecodeError:
                type_specs[cur_type][k] = v

    # Second pass: Resources Needed → instance_name → type_name
    instance_type: dict = {}
    in_needed = False
    cur_type = None

    for line in lines:
        s = line.rstrip("\n")
        if s == "\tResources Needed:":
            in_needed = True
            continue
        if not in_needed:
            continue
        if s.startswith("\t") and not s.startswith("\t\t") and s.strip():
            break
        if s.startswith("\t\tGeneral Type Name:"):
            cur_type = s.split(":", 1)[1].strip()
        elif cur_type and s.startswith("\t\t\t\t- "):
            inst = s[5:].strip()
            instance_type[inst] = cur_type

    # Combine
    result = {}
    for inst, gtype in instance_type.items():
        result[inst] = {
            "type": gtype,
            "specs": type_specs.get(gtype, {}),
        }
    return result


def _build_type_map(ext_filepath: str) -> dict:
    """
    Build type_name → {instance: first_instance_name, specs: dict} by parsing
    Resources Needed and Resources Infos sections directly from the file.

    This correctly handles types that share the same instance name
    (e.g. Screwdriver_1, Screwdriver_2, Screwdriver_3 all listing "Screwdriver"
    as their instance) — a case where inverting the instance→type map loses data.
    """
    with open(ext_filepath, encoding="utf-8") as f:
        lines = f.readlines()

    # Pass 1: Resources Infos → type_name → specs dict
    type_specs: dict = {}
    in_infos = False
    cur_type: str | None = None

    for line in lines:
        s = line.rstrip("\n")
        if s == "\tResources Infos:":
            in_infos = True
            continue
        if not in_infos:
            continue
        if s.startswith("\t") and not s.startswith("\t\t") and s.strip():
            break
        if s.startswith("\t\tGeneral Type Name:"):
            cur_type = s.split(":", 1)[1].strip()
            type_specs[cur_type] = {}
        elif cur_type and s.startswith("\t\t\t") and ":" in s:
            kv = s.strip().split(":", 1)
            k, v = kv[0].strip(), kv[1].strip()
            if k == "Quantity":
                continue
            try:
                type_specs[cur_type][k] = json.loads(v)
            except json.JSONDecodeError:
                type_specs[cur_type][k] = v

    # Pass 2: Resources Needed → type_name → first instance name
    result: dict = {}
    in_needed = False
    cur_type = None

    for line in lines:
        s = line.rstrip("\n")
        if s == "\tResources Needed:":
            in_needed = True
            continue
        if not in_needed:
            continue
        if s.startswith("\t") and not s.startswith("\t\t") and s.strip():
            break
        if s.startswith("\t\tGeneral Type Name:"):
            cur_type = s.split(":", 1)[1].strip()
        elif cur_type and s.startswith("\t\t\t\t- ") and cur_type not in result:
            inst = s[5:].strip()
            result[cur_type] = {
                "instance": inst,
                "specs": type_specs.get(cur_type, {}),
            }

    return result


def _infer_type(name: str) -> str:
    """Fallback: derive a general type name from an instance name."""
    return re.sub(r"\s+\d+\s*$", "", name).strip().replace(" ", "_") + "_1"
