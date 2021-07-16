from protean.core.field.basic import String
from protean.utils.container import BaseContainer


class CustomBaseContainer(BaseContainer):
    def __new__(cls, *args, **kwargs):
        if cls is CustomBaseContainer:
            raise TypeError("CustomBaseContainer cannot be instantiated")
        return super().__new__(cls)


class CustomContainer(CustomBaseContainer):
    foo = String(max_length=50, required=True)
    bar = String(max_length=50, required=True)
