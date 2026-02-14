import pytest

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


class UserLoggedIn(BaseEvent):
    user_id: str = Field(json_schema_extra={"identifier": True})


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
        foo: str | None = None

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
