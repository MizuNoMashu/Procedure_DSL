from .assemblyResource import AssemblyResource

class Tool(AssemblyResource):
    def __init__(self, name, detail):
        super().__init__(name, detail)
