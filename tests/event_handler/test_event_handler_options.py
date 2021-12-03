from protean import BaseAggregate, BaseEvent, BaseEventHandler
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
