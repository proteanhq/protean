import uuid

from protean.utils.container import BaseContainer


class Message(BaseContainer):
    """Base class for Events and Commands.

    It provides core implementations for:
    - ID generation
    - Payload construction
    - Serialization and De-serialization
    """

    def __new__(cls, *args, **kwargs):
        if cls is Message:
            raise TypeError("Message cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *template, owner, raise_errors, **kwargs):
        super().__init__(*template, owner=owner, raise_errors=raise_errors, **kwargs)

        # FIXME Should this identifier field be named something else?
        if "id" in kwargs:
            self.id = kwargs["id"]
        else:
            self.id = uuid.uuid4()
