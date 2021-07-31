import uuid

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.utils import fully_qualified_name

from .elements import NotifySSOSubscriber, PersonAdded


class TestSubscriberInitialization:
    def test_that_base_subscriber_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseSubscriber()

    def test_that_subscriber_can_be_instantiated(self, test_domain):
        service = NotifySSOSubscriber(
            test_domain,
            PersonAdded(
                **{
                    "id": uuid.uuid4(),
                    "first_name": "John",
                    "last_name": "Doe",
                    "age": 21,
                }
            ),
        )
        assert service is not None


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
