import pytest

from protean import BaseEventSourcedAggregate
from protean.fields import Integer, String
from protean.utils import DomainObjects, fully_qualified_name


class User(BaseEventSourcedAggregate):
    name = String()
    age = Integer()


def test_that_event_sourced_repository_is_returned_for_event_sourced_aggregate(
    test_domain,
):
    test_domain.register(User)

    assert (
        test_domain.repository_for(User).element_type
        == DomainObjects.EVENT_SOURCED_REPOSITORY
    )
