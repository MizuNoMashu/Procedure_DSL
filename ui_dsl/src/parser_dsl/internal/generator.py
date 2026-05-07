import json

from models.project import Project


def generate(project: Project):
    with open(f"{project.name}_internal_DSL.txt", "w") as file:
        for (step_id, step_obj) in project.step_object_json.items():
            prev_step = int(step_id) - 1

            comp_detail = step_obj.component.detail if step_obj.component.detail else {}
            comp_general = step_obj.component.changed_name  # e.g. "Frame_1"

            if step_obj.tool.name:
                tool_detail = step_obj.tool.detail if step_obj.tool.detail else {}
                tool_general = step_obj.tool.changed_name   # e.g. "Screwdriver_1"
                tool_part = f'.tool("{tool_general}","{step_obj.tool.name}",{json.dumps(tool_detail)})'
            else:
                tool_part = '.tool(None,None)'

            desc = step_obj.description.replace('"', '\\"')

            # Each line encodes one assembly step as a chain of function calls:
            # Step(N)                     - step index
            # .loadModel(N-1)             - reference to previous assembly state (0 = empty)
            # .loadPart(type, inst, det)  - general type name, instance name, component specs
            # .anchor([...])              - spatial alignment constraints (orientation)
            # .action(verb)               - assembly action (Place / Insert / Screw in / ...)
            # .on([...])                  - target components/subparts where action is applied
            # .tool(type, inst, det)      - tool type name, instance name, specs (None,None if none)
            # .desc(text)                 - human-readable description (mirrors external DSL)
            line = (
                f'Step({step_id})'
                f'.loadModel({prev_step})'
                f'.loadPart("{comp_general}","{step_obj.component.name}",{json.dumps(comp_detail)})'
                f'.anchor({json.dumps(step_obj.orientation)})'
                f'.action("{step_obj.action}")'
                f'.on({json.dumps(step_obj.applied_to)})'
                + tool_part +
                f'.desc("{desc}")'
            )

            file.write(line + "\n")
