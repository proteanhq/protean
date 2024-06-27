import uuid

import pytest

from protean import BaseEvent, BaseValueObject
from protean.exceptions import NotSupportedError
from protean.fields import String, ValueObject
from protean.utils import fully_qualified_name

from .elements import Person, PersonAdded


class TestDomainEventDefinition:
    def test_that_domain_event_can_accommodate_value_objects(self, test_domain):
        class Email(BaseValueObject):
            address = String(max_length=255)

        class UserAdded(BaseEvent):
            email = ValueObject(Email, required=True)
            name = String(max_length=50)

        test_domain.register(UserAdded, stream_name="user")
        event = UserAdded(email_address="john.doe@gmail.com", name="John Doe")

        assert event is not None
        assert event.email == Email(address="john.doe@gmail.com")
        assert event.email_address == "john.doe@gmail.com"

        assert (
            event.to_dict()
            == {
                "_metadata": {
                    "id": None,  # ID is none because the event is not being raised in the proper way (with `_raise`)
                    "timestamp": str(event._metadata.timestamp),
                    "version": "v1",
                    "sequence_id": None,  # Sequence is unknown as event is not being raised as part of an aggregate
                    "payload_hash": event._metadata.payload_hash,
                },
                "email": {
                    "address": "john.doe@gmail.com",
                },
                "name": "John Doe",
            }
        )

    def test_that_domain_event_can_be_reconstructed_from_dict_enclosing_vo(self):
        class Email(BaseValueObject):
            address = String(max_length=255)

        class UserAdded(BaseEvent):
            email = ValueObject(Email, required=True)
            name = String(max_length=50)

        assert UserAdded(
            {
                "email": {
                    "address": "john.doe@gmail.com",
                },
                "name": "John Doe",
            }
        ) == UserAdded(email_address="john.doe@gmail.com", name="John Doe")


class TestDomainEventInitialization:
    def test_that_base_domain_event_class_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseEvent()

    def test_that_domain_event_can_be_instantiated(self):
        service = PersonAdded(id=uuid.uuid4(), first_name="John", last_name="Doe")
        assert service is not None


class TestDomainEventRegistration:
    def test_that_domain_event_can_be_registered_with_domain(self, test_domain):
        test_domain.register(PersonAdded, part_of=Person)

        assert fully_qualified_name(PersonAdded) in test_domain.registry.events

    def test_that_domain_event_can_be_registered_via_annotations(self, test_domain):
        @test_domain.event(part_of=Person)
        class AnnotatedDomainEvent:
            def special_method(self):
                pass

        assert fully_qualified_name(AnnotatedDomainEvent) in test_domain.registry.events


class TestDomainEventEquivalence:
    def test_that_two_domain_events_with_same_values_are_considered_equal(self):
        identifier = uuid.uuid4()
        event_1 = PersonAdded(id=identifier, first_name="John", last_name="Doe")
        event_2 = PersonAdded(id=identifier, first_name="John", last_name="Doe")

        assert event_1 == event_2

    def test_that_two_domain_events_with_different_values_are_not_considered_equal(
        self,
    ):
        person1 = Person(id=uuid.uuid4(), first_name="John", last_name="Doe")
        person1.raise_(PersonAdded(id=person1.id, first_name="John", last_name="Doe"))

        person2 = Person(id=uuid.uuid4(), first_name="Jane", last_name="Doe")
        person2.raise_(PersonAdded(id=person2.id, first_name="Jane", last_name="Doe"))

        assert person1._events[0] != person2._events[0]

    def test_that_two_domain_events_with_different_values_are_not_considered_equal_with_different_types(
        self,
    ):
        identifier = uuid.uuid4()

        class User(Person):
            pass

        class UserAdded(PersonAdded):
            pass

        event_1 = PersonAdded(id=identifier, first_name="John", last_name="Doe")
        event_2 = UserAdded(id=identifier, first_name="John", last_name="Doe")

        assert event_1 != event_2
