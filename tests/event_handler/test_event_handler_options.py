import pytest

from protean import BaseAggregate, BaseEvent, BaseEventHandler
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String


class User(BaseAggregate):
    email = String()
    name = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()


def test_aggregate_cls_specified_during_registration(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, aggregate_cls=User)
    assert UserEventHandlers.meta_.aggregate_cls == User


def test_aggregate_cls_specified_as_a_meta_attribute(test_domain):
    class UserEventHandlers(BaseEventHandler):
        class Meta:
            aggregate_cls = User

    test_domain.register(UserEventHandlers)
    assert UserEventHandlers.meta_.aggregate_cls == User


def test_aggregate_cls_defined_via_annotation(
    test_domain,
):
    @test_domain.event_handler(aggregate_cls=User)
    class UserEventHandlers(BaseEventHandler):
        pass

    assert UserEventHandlers.meta_.aggregate_cls == User


def test_stream_name_option(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, stream_name="user")
    assert UserEventHandlers.meta_.stream_name == "user"


def test_options_defined_at_different_levels(test_domain):
    class UserEventHandlers(BaseEventHandler):
        class Meta:
            stream_name = "person"

    test_domain.register(UserEventHandlers, aggregate_cls=User)
    assert UserEventHandlers.meta_.aggregate_cls == User
    assert UserEventHandlers.meta_.stream_name == "person"


def test_that_a_default_stream_name_is_derived_from_aggregate_cls(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, aggregate_cls=User)
    assert UserEventHandlers.meta_.stream_name == "user"


def test_source_stream_option(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, aggregate_cls=User, source_stream="email")
    assert UserEventHandlers.meta_.source_stream == "email"


def test_that_aggregate_or_stream_name_has_to_be_specified(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    with pytest.raises(IncorrectUsageError):
        test_domain.register(UserEventHandlers)
