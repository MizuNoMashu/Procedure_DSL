class AssemblyResource:
    def __init__(self, name, detail):
        if(name.strip(" ") != ""):
            self.name = name
        else:
            self.name = None

        detail = detail.strip(" ").rstrip(";").split(";")
        #if there are details create a dictionary with each element, an element is key = value
        if detail != ['']:
            final_detail_dict = {}
            for detail_elem in detail:
                detail_elem = detail_elem.strip(" ").split("=", 1)
                if len(detail_elem) == 2:
                    final_detail_dict[detail_elem[0].strip(" ")] = detail_elem[1].strip(" ")
            self.detail = final_detail_dict
        else:
            self.detail = None

        self.changed_name = ""

    def __str__(self):
        return str(self.name) + " " + str(self.detail)


    def change_name(self, new_name):
        self.changed_name = new_name
