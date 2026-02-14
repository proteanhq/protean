import uuid

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError, NotSupportedError, ValidationError
from protean.fields import Identifier, String, ValueObject
from protean.utils import fully_qualified_name
from protean.utils.eventing import MessageEnvelope
from protean.utils.reflection import data_fields, declared_fields, fields

from .elements import Person, PersonAdded


class TestDomainEventDefinition:
    def test_domain_event_dict_keys(self):
        assert all(
            key in declared_fields(PersonAdded)
            for key in ["first_name", "last_name", "age", "id"]
        )
        assert all(
            key in data_fields(PersonAdded)
            for key in ["first_name", "last_name", "age", "id"]
        )
        assert all(
            key in fields(PersonAdded)
            for key in ["first_name", "last_name", "age", "id"]
        )

    def test_that_domain_event_can_accommodate_value_objects(self, test_domain):
        class Email(BaseValueObject):
            address: String(max_length=255)

        class User(BaseAggregate):
            email = ValueObject(Email, required=True)
            name: String(max_length=50)

        class UserAdded(BaseEvent):
            id: Identifier(identifier=True)
            email: Email | None = None
            name: str | None = None

        test_domain.register(User)
        test_domain.register(UserAdded, part_of=User)
        test_domain.init(traverse=False)

        user = User(
            id=str(uuid.uuid4()),
            email=Email(address="john.doe@gmail.com"),
            name="John Doe",
        )
        raw_event = UserAdded(
            id=user.id, email=Email(address="john.doe@gmail.com"), name=user.name
        )
        user.raise_(
            UserAdded(
                id=user.id, email=Email(address="john.doe@gmail.com"), name=user.name
            )
        )
        raised_event = user._events[0]

        assert raw_event is not None
        assert raw_event.email == Email(address="john.doe@gmail.com")

        assert (
            raw_event.to_dict()
            == {
                "_metadata": {
                    "envelope": {
                        "specversion": "1.0",
                        "checksum": None,
                    },
                    "headers": {
                        "id": None,  # ID is none because the event is not being raised in the proper way (with `_raise`)
                        "type": "Test.UserAdded.v1",
                        "stream": None,  # Stream is none here because of the same reason as above
                        "time": str(raw_event._metadata.headers.time),
                        "traceparent": None,
                        "idempotency_key": None,
                    },
                    "domain": {
                        "fqn": fully_qualified_name(UserAdded),
                        "kind": "EVENT",
                        "origin_stream": None,
                        "stream_category": None,
                        "version": "v1",
                        "sequence_id": None,
                        "asynchronous": True,  # Asynchronous is True by default
                        "expected_version": None,
                    },
                    "event_store": None,
                },
                "email": {
                    "address": "john.doe@gmail.com",
                },
                "name": "John Doe",
                "id": user.id,
            }
        )

        # Compute expected checksum
        expected_checksum = MessageEnvelope.compute_checksum(raised_event.payload)

        assert raised_event.to_dict() == {
            "_metadata": {
                "envelope": {
                    "specversion": "1.0",
                    "checksum": expected_checksum,
                },
                "headers": {
                    "id": f"test::user-{user.id}-0.1",
                    "type": "Test.UserAdded.v1",
                    "stream": f"test::user-{user.id}",
                    "time": str(raised_event._metadata.headers.time),
                    "traceparent": None,
                    "idempotency_key": None,
                },
                "domain": {
                    "fqn": fully_qualified_name(UserAdded),
                    "kind": "EVENT",
                    "origin_stream": None,
                    "stream_category": "test::user",
                    "version": "v1",
                    "sequence_id": "0.1",
                    "asynchronous": False,
                    "expected_version": None,
                },
                "event_store": None,
            },
            "email": {
                "address": "john.doe@gmail.com",
            },
            "name": "John Doe",
            "id": user.id,
        }

    def test_error_on_invalid_value_object(self, test_domain):
        class Address(BaseValueObject):
            street: String(max_length=50, required=True)
            city: String(max_length=25, required=True)

        class Person(BaseAggregate):
            name: String(max_length=50)
            address = ValueObject(Address, required=True)

        class PersonAdded(BaseEvent):
            id: Identifier(identifier=True)
            name: str | None = None
            address: Address | None = None

        test_domain.register(PersonAdded, part_of=Person)
        test_domain.init(traverse=False)

        with pytest.raises(ValidationError) as exc:
            PersonAdded(
                id=str(uuid.uuid4()),
                name="John Doe",
                address={"street": "123 Main St"},
            )

        assert exc.value.messages == {"city": ["is required"]}

    def test_that_domain_event_can_be_reconstructed_from_dict_enclosing_vo(
        self, test_domain
    ):
        class Email(BaseValueObject):
            address: String(max_length=255)

        class User(BaseAggregate):
            email = ValueObject(Email, required=True)
            name: String(max_length=50)

        class UserAdded(BaseEvent):
            email: Email | None = None
            name: str | None = None

        test_domain.register(User)
        test_domain.register(UserAdded, part_of=User)
        test_domain.init(traverse=False)

        assert UserAdded(
            {
                "email": Email(address="john.doe@gmail.com"),
                "name": "John Doe",
            }
        ) == UserAdded(email=Email(address="john.doe@gmail.com"), name="John Doe")


class TestDomainEventInitialization:
    def test_that_base_domain_event_class_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseEvent()

    def test_that_domain_event_can_be_instantiated(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonAdded, part_of=Person)
        test_domain.init(traverse=False)

        service = PersonAdded(id=str(uuid.uuid4()), first_name="John", last_name="Doe")
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

    def test_domain_stores_event_type_for_easy_retrieval(self, test_domain):
        test_domain.register(PersonAdded, part_of=Person)
        test_domain.init(traverse=False)

        assert PersonAdded.__type__ in test_domain._events_and_commands

    def test_registering_external_event(self, test_domain):
        class ExternalEvent(BaseEvent):
            foo: String()

        test_domain.register_external_event(ExternalEvent, "Bar.ExternalEvent.v1")

        assert "Bar.ExternalEvent.v1" in test_domain._events_and_commands
        assert fully_qualified_name(ExternalEvent) not in test_domain.registry.events

    def test_registering_invalid_external_event_class(self, test_domain):
        class Dummy:
            pass

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register_external_event(Dummy, "Bar.ExternalEvent.v1")

        assert exc.value.args[0] == "Class `Dummy` is not an Event"


class TestDomainEventEquivalence:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonAdded, part_of=Person)
        test_domain.init(traverse=False)

    def test_that_two_domain_events_with_same_values_are_considered_equal(self):
        identifier = str(uuid.uuid4())
        event_1 = PersonAdded(id=identifier, first_name="John", last_name="Doe")
        event_2 = PersonAdded(id=identifier, first_name="John", last_name="Doe")

        assert event_1 == event_2

    def test_that_two_domain_events_with_different_values_are_not_considered_equal(
        self,
    ):
        person1 = Person(id=str(uuid.uuid4()), first_name="John", last_name="Doe")
        person1.raise_(PersonAdded(id=person1.id, first_name="John", last_name="Doe"))

        person2 = Person(id=str(uuid.uuid4()), first_name="Jane", last_name="Doe")
        person2.raise_(PersonAdded(id=person2.id, first_name="Jane", last_name="Doe"))

        assert person1._events[0] != person2._events[0]

    def test_that_two_domain_events_with_different_values_are_not_considered_equal_with_different_types(
        self,
    ):
        identifier = str(uuid.uuid4())

        class User(Person):
            pass

        class UserAdded(PersonAdded):
            pass

        event_1 = PersonAdded(id=identifier, first_name="John", last_name="Doe")
        event_2 = UserAdded(id=identifier, first_name="John", last_name="Doe")

        assert event_1 != event_2
