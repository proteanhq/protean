import pytest

from protean.core.event import BaseEvent
from protean.core.field.basic import Identifier, Integer, String
from protean.core.subscriber import BaseSubscriber
from protean.utils import fully_qualified_name


class PersonAdded(BaseEvent):
    id = Identifier(required=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class NotifySSOSubscriber(BaseSubscriber):
    """Subscriber that notifies an external SSO system
    that a new person was added into the system
    """

    class Meta:
        event = PersonAdded

    def notify(self, event):
        print("Received Event: ", event)


class TestSubscriberInitialization:
    def test_that_base_subscriber_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseSubscriber()

    def test_that_subscriber_can_be_instantiated(self, test_domain):
        subscriber = NotifySSOSubscriber()
        assert subscriber is not None


class TestSubscriberRegistration:
    def test_that_domain_event_can_be_registered_with_domain(self, test_domain):
        test_domain.register(NotifySSOSubscriber)

        assert (
            fully_qualified_name(NotifySSOSubscriber)
            in test_domain.registry.subscribers
        )

    def test_that_domain_event_can_be_registered_via_annotations(self, test_domain):
        @test_domain.subscriber(event=PersonAdded)
        class AnnotatedSubscriber:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedSubscriber)
            in test_domain.registry.subscribers
        )
