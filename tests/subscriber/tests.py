# Protean
import pytest

from mock import patch
from protean.core.broker.subscriber import BaseSubscriber
from protean.utils import fully_qualified_name

# Local/Relative Imports
from .elements import NotifySSOSubscriber, Person, PersonAdded


class TestSubscriberInitialization:
    def test_that_base_subscriber_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseSubscriber()

    def test_that_subscriber_can_be_instantiated(self, test_domain):
        service = NotifySSOSubscriber(test_domain, PersonAdded())
        assert service is not None


class TestApplicationServiceRegistration:
    def test_that_domain_event_can_be_registered_with_domain(self, test_domain):
        test_domain.register(NotifySSOSubscriber)

        assert fully_qualified_name(NotifySSOSubscriber) in test_domain.subscribers

    def test_that_domain_event_can_be_registered_via_annotations(self, test_domain):
        @test_domain.subscriber(domain_event=PersonAdded)
        class AnnotatedSubscriber:
            def special_method(self):
                pass

        assert fully_qualified_name(AnnotatedSubscriber) in test_domain.subscribers


class TestDomainEventNotification:
    @patch.object(NotifySSOSubscriber, "notify")
    def test_that_domain_event_is_received_from_aggregate_command_method(
        self, mock, test_domain
    ):
        test_domain.register(NotifySSOSubscriber)

        newcomer = Person.add_newcomer(
            {"first_name": "John", "last_name": "Doe", "age": 21}
        )
        mock.assert_called_once_with(PersonAdded(person=newcomer).to_dict())
