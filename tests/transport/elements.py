# Protean
from protean.core.transport import BaseRequestObject


class DummyValidRequestObject(BaseRequestObject):
    """ Dummy Request object for testing"""
    @classmethod
    def from_dict(cls, entity, adict):
        """Initialize a Request object from a dictionary."""
        pass
