import pytest

from protean import BaseAggregate, BaseEvent, BaseEventHandler
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Identifier, String


class User(BaseAggregate):
    email = String()
    name = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()


def test_that_base_command_handler_cannot_be_instantianted():
    with pytest.raises(NotSupportedError):
        BaseEventHandler()


def test_part_of_specified_during_registration(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, part_of=User)
    assert UserEventHandlers.meta_.part_of == User


def test_part_of_specified_as_a_meta_attribute(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, part_of=User)
    assert UserEventHandlers.meta_.part_of == User


def test_part_of_defined_via_annotation(
    test_domain,
):
    @test_domain.event_handler(part_of=User)
    class UserEventHandlers(BaseEventHandler):
        pass

    assert UserEventHandlers.meta_.part_of == User


def test_stream_name_option(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, stream_name="user")
    assert UserEventHandlers.meta_.stream_name == "user"


def test_options_defined_at_different_levels(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, part_of=User, stream_name="person")
    assert UserEventHandlers.meta_.part_of == User
    assert UserEventHandlers.meta_.stream_name == "person"


def test_that_a_default_stream_name_is_derived_from_part_of(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(User)
    test_domain.register(UserEventHandlers, part_of=User)
    assert UserEventHandlers.meta_.stream_name == "user"


def test_source_stream_option(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    test_domain.register(UserEventHandlers, part_of=User, source_stream="email")
    assert UserEventHandlers.meta_.source_stream == "email"


def test_that_aggregate_or_stream_name_has_to_be_specified(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    with pytest.raises(IncorrectUsageError):
        test_domain.register(UserEventHandlers)
