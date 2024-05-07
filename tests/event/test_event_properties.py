import pytest

from protean import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String


class Registered(BaseEvent):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


def test_that_events_are_immutable():
    event = Registered(email="john.doe@gmail.com", name="John Doe", user_id="1234")
    with pytest.raises(IncorrectUsageError):
        event.name = "Jane Doe"
