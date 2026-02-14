import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event_sourced_repository import BaseEventSourcedRepository
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, String
from protean.utils import DomainObjects


class User(BaseAggregate):
    name: String()
    age: Integer()


def test_that_event_sourced_repository_is_returned_for_event_sourced_aggregate(
    test_domain,
):
    test_domain.register(User, is_event_sourced=True)

    assert (
        test_domain.repository_for(User).element_type
        == DomainObjects.EVENT_SOURCED_REPOSITORY
    )


def test_that_a_custom_repository_cannot_be_associated_with_event_sourced_aggregates(
    test_domain,
):
    class CustomUserRepository(BaseEventSourcedRepository):
        pass

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(CustomUserRepository)

    assert (
        exc.value.args[0]
        == "Repository `CustomUserRepository` should be associated with an Aggregate"
    )


def test_that_an_event_sourced_repository_can_only_be_associated_with_an_event_sourced_aggregate(
    test_domain,
):
    class CustomAggregate(BaseAggregate):
        pass

    class CustomRepository(BaseEventSourcedRepository):
        pass

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(CustomAggregate)
        test_domain.register(CustomRepository, part_of=CustomAggregate)

    assert exc.value.args[0] == (
        "Repository `CustomRepository` can only be associated with an Event Sourced Aggregate"
    )
