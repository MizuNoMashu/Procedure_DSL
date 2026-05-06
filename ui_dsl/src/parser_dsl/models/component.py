from .assemblyResource import AssemblyResource

class Component(AssemblyResource):
    def __init__(self, name, detail):
        super().__init__(name, detail)
