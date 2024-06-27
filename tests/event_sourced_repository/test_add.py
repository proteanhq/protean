import pytest

from protean import BaseEventSourcedAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.init(traverse=False)


def test_exception_on_empty_aggregate_object(test_domain):
    with pytest.raises(IncorrectUsageError) as exception:
        test_domain.repository_for(User).add(None)

    assert exception.value.messages == {
        "_entity": ["Aggregate object to persist is invalid"]
    }
