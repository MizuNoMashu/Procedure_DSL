from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project import Project

import copy
import json


class AssemblyStep:
    def __init__(self, name, component, tool, orientation, action, applied_to, detail, project: 'Project' ):
        self.name = name
        self.component = component
        self.tool = tool
        self.action = action
        self.project = project

        self.component_json = {}
        self.tool_json = {}
        if(self.tool.name != None):
            self.tool_json[self.tool.name] = self.tool
        self.component_json[self.component.name] = self.component
            # print(self.project.resources_original_json[self.tool.name])
            # self.tool_json[]


        self.applied_to = self.extract_destination(applied_to)
        self.orientation = self.analyze_orientation(orientation)


        if detail != None and detail.strip(" ") != "":
            self.description = detail
        else:
            self.description = self.build_description()

        self.detail = {}
        if(int(self.get_step_number_str()) == 1):
            # self.detail["result"] = self.component.detail
            self.detail[self.component.name] = copy.deepcopy(self.component.detail)
        else:
            self.detail = copy.deepcopy(self.project.step_object_json[str(int(self.get_step_number_str())-1)].detail)
            self.build_detail()
        # self.detail[self.component.changed_name] = self.project.extract_information(self.component.changed_name)


    # def build_detail(self,)
            
    def analyze_orientation(self, orientation):
        orientation = orientation.strip(" ").split(";")
        orientation_array = []

        #for each element to align
        for elements in orientation:

            #if there is still an element to align
            if elements.strip(" ") != "":
                if "=" in elements:
                    elements = elements.split("=")
                    component_detail = elements[0].strip(" ")

                    #if the detail of component not in the object detail insert it
                    if(component_detail not in self.project.extract_information(self.component.changed_name).keys()):
                        self.project.insert_information(self.component.name,self.component.changed_name,component_detail)
                    
                    #if destination to align has details
                    if "." in elements[1]:
                        applied_to = elements[1].strip(" ").split(".")
                        applied_to_component_original = applied_to[0].strip(" ")
                        applied_to_component = self.project.resources_original_json[applied_to_component_original]
                        applied_to_detail = applied_to[1].strip(" ")
                        if(applied_to_detail not in self.project.extract_information(applied_to_component).keys()):
                            self.project.insert_information(applied_to_component_original,applied_to_component,applied_to_detail)
                        orientation_array.append([component_detail,applied_to_component_original,applied_to_detail])
                        if(applied_to_component_original not in self.component_json.keys()):
                            self.component_json[applied_to_component_original] = self.project.resources_object_json[applied_to_component][applied_to_component_original]
                    else:
                        applied_to_component_original = elements[1].strip(" ")
                        orientation_array.append([component_detail,applied_to_component_original])
                        applied_to_component = self.project.resources_original_json[applied_to_component_original]
                        if(applied_to_component_original not in self.component_json.keys()):
                            self.component_json[applied_to_component_original] = self.project.resources_object_json[applied_to_component][applied_to_component_original]
                else:
                    print("Non c'è uguale in orientation")
        return orientation_array

            
    def extract_destination(self, applied_to):
        applied_to = applied_to.strip(" ").split(";")
        applied_to_array = []
        for elements in applied_to:
            if elements.strip(" ") != "":
                if "." in elements:
                    #update project
                    elements = elements.split(".")
                    component_original = elements[0].strip(" ")
                    component_detail = elements[1].strip(" ")

                    component = self.project.resources_original_json[component_original]
                    if(component_detail not in self.project.extract_information(component).keys()):
                        self.project.insert_information(component_original,component,component_detail)
                    applied_to_array.append([component_original, component_detail])

                    if(component_original not in self.component_json.keys()):
                        self.component_json[component_original] = self.project.resources_object_json[component][component_original]
                else:
                    elements = elements.strip(" ")
                    applied_to_array.append([elements])

                    elements_changed = self.project.resources_original_json[elements]
                    if(elements not in self.component_json.keys()):
                        self.component_json[elements] = self.project.resources_object_json[elements_changed][elements]
        return applied_to_array
    
    def build_description(self):
        final_detail = "Take " + self.component.name
        final_detail+= self.orientation_detail()
        if(final_detail != ""):
            final_detail+= ". "
        
        match self.action:
            case "Place":
                final_detail+= "Place in "
            case "Insert":
                final_detail+= "Insert in "
            case "Screw in":
                final_detail+= "Screw in "
            case _:
                pass

        final_detail+= self.applied_to_detail()
        final_detail+="."
        return final_detail

    def orientation_detail(self):
        orientation_len = len(self.orientation)
        current_element_number = 1
        orientation_detail = ""
        if(orientation_len >= 1):
            orientation_detail+= " and align "
        for element in self.orientation:
            if(current_element_number == orientation_len and current_element_number > 1):
                orientation_detail+=" and "
            if(len(element) == 2):
                orientation_detail+= element[0] + " with " + element[1]
            else:
                orientation_detail+= element[0] + " with " + element[2] + " of " + element[1]
            if(current_element_number != orientation_len -1 and orientation_len > 2 and current_element_number != orientation_len):
                orientation_detail+=", "
            current_element_number+=1
        return orientation_detail
    
    def applied_to_detail(self):
        applied_to_len = len(self.applied_to)
        current_element_number = 1
        applied_to_detail = ""
        for element in self.applied_to:
            if(current_element_number == applied_to_len  and current_element_number > 1): #last element
                applied_to_detail+= " and "
            if(len(element) == 2):
                applied_to_detail+= element[1] + " of " + element[0] 
            else:
                applied_to_detail+= element[0] 
            if(current_element_number != applied_to_len - 1 and applied_to_len > 2 and current_element_number != applied_to_len):
                applied_to_detail+=", "
            current_element_number+=1
        return applied_to_detail
    
    '''
    component is the one that need to be inserted in the detail json
    applied to is 
    '''
    def build_detail(self):
        # print(str(self.applied_to))
        # print(str(self.action))
        # for 
        self.detail[self.component.name] = self.component.detail
        for destination_element in self.applied_to:
            if(len(destination_element) == 1):
                if("Resources" not in self.detail[destination_element[0]].keys()):
                    self.detail[destination_element[0]]["Resources"] = [[self.get_step_number_str(),self.component.name]]
                else:
                    self.detail[destination_element[0]]["Resources"].append([[self.get_step_number_str(),self.component.name]])
            else:
                if(destination_element[1] not in self.detail[destination_element[0]].keys()):
                    self.detail[destination_element[0]][destination_element[1]] = [[self.get_step_number_str(),self.component.name]]
                else:
                    self.detail[destination_element[0]][destination_element[1]].append([[self.get_step_number_str(),self.component.name]])
        
    #return the current step number
    def get_step_number_str(self):
        return self.name.split("_")[1]

    def __str__(self):
        return self.name + "\n" + self.description + "\n" + str(self.tool_json) + "\n" + str(self.component_json) + "\n" + json.dumps(self.detail,indent=4) + "\n"