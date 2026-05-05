import csv
import sys
import os

from models.component import Component
from models.tool import Tool
from models.project import Project
from models.assemblyStep import AssemblyStep

from external.generator import generate as generate_external
from internal.generator import generate as generate_internal


def main(input_file, project_name):
    project_cubesat = Project(project_name)
    num_step = 1

    with open(input_file, "r") as file:
        csv_reader = csv.reader(file)
        next(csv_reader, None)

        for row in csv_reader:
            col_component        = row[1]
            col_component_detail = row[2]
            col_orientation      = row[3]
            col_action           = row[4]
            col_applied_to       = row[5]
            col_tool             = row[6]
            col_tool_detail      = row[7]
            col_assembly_detail  = row[8]

            step_name = "Step_" + str(num_step)

            component_obj = Component(col_component, col_component_detail)
            tool_obj = Tool(col_tool, col_tool_detail)

            project_cubesat.composed_by(component_obj)
            project_cubesat.composed_by(tool_obj)

            step_obj = AssemblyStep(step_name, component_obj, tool_obj, col_orientation, col_action,
                                    col_applied_to, col_assembly_detail, project_cubesat)

            project_cubesat.has_step(step_obj, num_step)
            num_step += 1

    generate_external(project_cubesat)
    generate_internal(project_cubesat)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python main.py -csv <file_path> <project_name>")
        print("Usage: python main.py -help")
        sys.exit(1)
    elif sys.argv[1] == "-help":
        print("I'm helping you!")
    elif sys.argv[1] == "-csv":
        input_file = sys.argv[2]
        if os.path.exists(input_file):
            project_name = sys.argv[3]
            main(input_file, project_name)
        else:
            print("File not found!")
