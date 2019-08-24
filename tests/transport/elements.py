# Protean
from protean.core.field.basic import String
from protean.core.transport import BaseRequestObject


class DummyValidRequestObject(BaseRequestObject):
    """ Dummy Request object for testing"""
    foo = String(max_length=15)
