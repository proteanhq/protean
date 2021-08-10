import uuid

import pytest

from protean.core.event import BaseEvent
from protean.exceptions import NotSupportedError
from protean.globals import current_domain
from protean.infra.eventing import EventLog, EventLogRepository
from protean.utils import fully_qualified_name
from tests.test_brokers import AddPersonCommand

from .elements import Person, PersonAdded, PersonCommand, PersonService


class TestDomainEventInitialization:
    def test_that_base_domain_event_class_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseEvent()

    def test_that_domain_event_can_be_instantiated(self):
        service = PersonAdded(id=uuid.uuid4(), first_name="John", last_name="Doe")
        assert service is not None


class TestDomainEventRegistration:
    def test_that_domain_event_can_be_registered_with_domain(self, test_domain):
        test_domain.register(PersonAdded)

        assert fully_qualified_name(PersonAdded) in test_domain.registry.events

    def test_that_domain_event_can_be_registered_via_annotations(self, test_domain):
        @test_domain.event(aggregate_cls=Person)
        class AnnotatedDomainEvent:
            def special_method(self):
                pass

        assert fully_qualified_name(AnnotatedDomainEvent) in test_domain.registry.events


class TestDomainEventTriggering:
    def test_that_domain_event_is_raised_in_aggregate_command_method(self, test_domain):
        test_domain.register(Person)
        test_domain.register(EventLog)
        test_domain.register(EventLogRepository)
        test_domain.register(AddPersonCommand)
        test_domain.register(PersonAdded)
        person = Person.add_newcomer(
            {"first_name": "John", "last_name": "Doe", "age": 21}
        )

        event_repo = current_domain.repository_for(EventLog)
        event = event_repo.get_most_recent_event_by_type_cls(event_cls=PersonAdded)

        assert event is not None
        assert event.name == "PersonAdded"
        assert event.type == "EVENT"
        assert event.payload == person.to_dict()

    def test_that_domain_event_is_persisted(self, test_domain):
        test_domain.register(Person)
        test_domain.register(EventLog)
        test_domain.register(EventLogRepository)
        test_domain.register(AddPersonCommand)
        test_domain.register(PersonAdded)

        command = PersonCommand(first_name="John", last_name="Doe", age=21)
        person = PersonService.add(command)

        event_repo = current_domain.repository_for(EventLog)
        event = event_repo.get_most_recent_event_by_type_cls(event_cls=PersonAdded)

        assert event is not None
        assert event.name == "PersonAdded"
        assert event.type == "EVENT"
        assert event.payload == person.to_dict()

    def test_that_all_events_are_retrievable(self, test_domain):
        test_domain.register(Person)
        test_domain.register(EventLog)
        test_domain.register(EventLogRepository)
        test_domain.register(AddPersonCommand)
        test_domain.register(PersonAdded)

        command = PersonCommand(first_name="John", last_name="Doe", age=21)
        person = PersonService.add(command)

        event_repo = current_domain.repository_for(EventLog)
        events = event_repo.get_all_events_of_type_cls(event_cls=PersonAdded)

        assert events is not None
        assert isinstance(events, list)
        assert len(events) == 1
        assert events[0].name == "PersonAdded"
        assert events[0].type == "EVENT"
        assert events[0].payload == person.to_dict()
