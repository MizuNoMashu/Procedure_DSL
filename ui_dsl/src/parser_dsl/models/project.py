from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .assemblyResource import AssemblyResource
    from .assemblyStep import AssemblyStep

import json
import copy
import re


class Project:
    def __init__(self, name):
        self.resources_json = {}
        self.resources_original_json = {}
        #changed_name -> original_name -> object
        self.resources_object_json = {}
        self.step_object_json = {}
        self.name = name

    def composed_by(self, resource: 'AssemblyResource'):
        if resource.name is None:
            return
        if resource.detail is None:
            # Register name mapping to prevent KeyError on future lookups
            if resource.name not in self.resources_original_json:
                resource_general_name = re.sub(r'\d+$', '', resource.name).strip(" ")
                new_resource_name = resource_general_name + "_1"
                self.resources_original_json[resource.name] = new_resource_name
                resource.change_name(new_resource_name)
            else:
                resource.change_name(self.resources_original_json[resource.name])
            return
        resource_general_name = re.sub(r'\d+$','',resource.name).strip(" ")
        record_found = self.find_resource(resource_general_name, resource.detail)

        if record_found == (None, None, None):
            self.resources_json[resource_general_name] = {}
            self.resources_json[resource_general_name][1] = copy.deepcopy(resource.detail)
            self.resources_json[resource_general_name][1]["Quantity"] = 1
            new_resource_name = resource_general_name + "_1"
            self.resources_original_json[resource.name] = new_resource_name
            resource.change_name(new_resource_name)
            self.resources_object_json[new_resource_name] = {}
            self.resources_object_json[new_resource_name][resource.name] = resource
        elif record_found[2] == None:
            self.resources_json[resource_general_name][record_found[1]+1] = copy.deepcopy(resource.detail)
            self.resources_json[resource_general_name][record_found[1]+1]["Quantity"] = 1
            new_resource_name = resource_general_name + "_" + str(record_found[1]+1)
            self.resources_original_json[resource.name] = new_resource_name
            resource.change_name(new_resource_name)
            self.resources_object_json[new_resource_name] = {}
            self.resources_object_json[new_resource_name][resource.name] = resource
        else:
            self.resources_json[resource_general_name][record_found[1]] = copy.deepcopy(resource.detail)
            self.resources_json[resource_general_name][record_found[1]]["Quantity"] = record_found[2] + 1
            new_resource_name = resource_general_name + "_" + str(record_found[1])
            self.resources_original_json[resource.name] = new_resource_name
            resource.change_name(new_resource_name)
            self.resources_object_json[new_resource_name][resource.name] = resource


    #(None,None,None) if there is no record of name
    #(Name,id,None) if there is a record of name but not with same detail, return last id
    #(Name,id,quantity) if there is wanted record with some quantity
    def find_resource(self, name, detail):
        if name not in self.resources_json.keys():
            return (None, None, None)

        flag_record_found = False
        last_component_id = 1

        for (component_id, component_detail) in self.resources_json[name].items():
            last_component_id = component_id
            # Exclude Quantity and dynamically added keys (value=[]) from comparison
            stored_original = {k: v for k, v in component_detail.items()
                               if k != "Quantity" and v != []}
            # Bidirectional check: same key set and same values
            if stored_original.keys() == detail.keys():
                flag_record_found = all(detail[k] == v for k, v in stored_original.items())
            else:
                flag_record_found = False
            if flag_record_found:
                return (name, last_component_id, component_detail["Quantity"])

        return (name, last_component_id, None)

    #extract details from general json resources
    def extract_information(self, name):
        name = name.split("_")
        return self.resources_json[name[0]][int(name[1])]

    #insert information in both object and project resources, just the key
    def insert_information(self, name_original, name, detail):
        self.resources_object_json[name][name_original].detail[detail] = []
        name = name.split("_")
        self.resources_json[name[0]][int(name[1])][detail] = []

    #insert the object of the class AssemblyStep in the dictionary in pos step_id
    def has_step(self, step_obj, step_id):
        self.step_object_json[str(step_id)] = step_obj

    def extract_resources_infos(self):
        extracted_resources_needed_text = ""
        extracted_resources_infos_text = ""

        extracted_resources_needed_text += "\tResources Needed:\n"
        extracted_resources_infos_text += "\tResources Infos:\n"
        for (general_name, general_json) in self.resources_json.items():
            for (number, details) in general_json.items():
                general_type_name = f"{general_name}_{number}"
                extracted_resources_needed_text += f"\t\tGeneral Type Name: {general_type_name}\n"
                extracted_resources_infos_text += f"\t\tGeneral Type Name: {general_type_name}\n"
                for (key,value) in details.items():
                    if(key == "Quantity"):
                        extracted_resources_needed_text += f"\t\t\t{key}: {value}\n"
                        extracted_resources_infos_text += f"\t\t\t{key}: {value}\n"
                    else:
                        extracted_resources_infos_text += f"\t\t\t{key}: {value}\n"
                extracted_resources_needed_text += f"\t\t\tInstances:\n"
                for instances in self.resources_object_json[f"{general_type_name}"].keys():
                    extracted_resources_needed_text += f"\t\t\t\t- {instances}\n"

        return extracted_resources_needed_text, extracted_resources_infos_text

    def extract_step_infos(self):
        extracted_step_infos_text = ""

        extracted_step_infos_text += "\tAssembly Steps:\n"
        step_object: 'AssemblyStep'
        for (step,step_object) in self.step_object_json.items():
            extracted_step_infos_text += f"\t\tStep number: {step}\n"
            extracted_step_infos_text += f"\t\t\tDescription: {step_object.description}\n"

            extracted_step_infos_text += f"\t\t\tInvolved Components: {step_object.component.name},"
            counter = 1
            for involved_component in step_object.applied_to:
                extracted_step_infos_text += f" {involved_component[0]}"
                if counter < len(step_object.applied_to):
                    counter+=1
                    extracted_step_infos_text += f","
            extracted_step_infos_text +="\n"

        return extracted_step_infos_text

    def __str__(self):
        return_value = "Project name is: " + self.name + "\n"
        return_value += "Resources invovled are:\n" + json.dumps(self.resources_json, indent=4)
        return return_value
