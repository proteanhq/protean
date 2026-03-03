import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class UserLoggedIn(BaseEvent):
    user_id: Identifier(identifier=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)


def test_event_definition_without_aggregate_or_stream(test_domain):
    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(UserLoggedIn)

    assert (
        exc.value.args[0]
        == "Event `UserLoggedIn` needs to be associated with an aggregate or a stream"
    )


def test_that_abstract_events_can_be_defined_without_aggregate_or_stream(test_domain):
    class AbstractEvent(BaseEvent):
        foo: String()

    try:
        test_domain.register(AbstractEvent, abstract=True)
    except Exception:
        pytest.fail(
            "Abstract events should be definable without being associated with an aggregate or a stream"
        )


def test_that_part_of_is_resolved_correctly():
    assert UserLoggedIn.meta_.part_of == User


def test_aggregate_cluster_of_event():
    assert UserLoggedIn.meta_.aggregate_cluster == User


class TestPublishedOption:
    def test_published_defaults_to_false(self):
        assert UserLoggedIn.meta_.published is False

    def test_published_true_is_accepted(self, test_domain):
        class OrderPlaced(BaseEvent):
            order_id: Identifier(identifier=True)

        test_domain.register(OrderPlaced, part_of=User, published=True)

        assert OrderPlaced.meta_.published is True

    def test_published_false_is_accepted(self, test_domain):
        class InternalEvent(BaseEvent):
            data: String()

        test_domain.register(InternalEvent, part_of=User, published=False)

        assert InternalEvent.meta_.published is False

    def test_invalid_published_raises_error(self, test_domain):
        class BadEvent(BaseEvent):
            data: String()

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(BadEvent, part_of=User, published="yes")

        assert "invalid `published` option" in exc.value.args[0]
