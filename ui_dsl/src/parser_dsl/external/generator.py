from models.project import Project


def generate(project: Project):
    with open(f"{project.name}_external_DSL.yml", "w") as file:
        file.write(f"Project: {project.name}\n")
        extracted_resources = project.extract_resources_infos()
        file.write(extracted_resources[0])
        file.write(project.extract_step_infos())
        file.write(extracted_resources[1])
