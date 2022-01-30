import pytest

from protean import BaseEventSourcedAggregate
from protean.core.event_sourced_repository import BaseEventSourcedRepository
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, Integer, String
from protean.utils import DomainObjects


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach identifier
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


def test_that_a_custom_repository_cannot_be_associated_with_event_sourced_aggregates(
    test_domain,
):
    class CustomUserRepository(BaseEventSourcedRepository):
        class Meta:
            aggregate_cls = User

    with pytest.raises(IncorrectUsageError):
        test_domain.register(CustomUserRepository)
