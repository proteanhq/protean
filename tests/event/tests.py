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

        test_domain.register(UserAdded)
        event = UserAdded(email_address="john.doe@gmail.com", name="John Doe")

        assert event is not None
        assert event.email == Email(address="john.doe@gmail.com")
        assert event.email_address == "john.doe@gmail.com"

        assert event.to_dict() == {
            "email": {
                "address": "john.doe@gmail.com",
            },
            "name": "John Doe",
        }

    def test_that_domain_event_can_be_reconstructed_from_dict_enclosing_vo(self):
        class Email(BaseValueObject):
            address = String(max_length=255)

        class UserAdded(BaseEvent):
            email = ValueObject(Email, required=True)
            name = String(max_length=50)

        assert (
            UserAdded(
                {
                    "email": {
                        "address": "john.doe@gmail.com",
                    },
                    "name": "John Doe",
                }
            )
            == UserAdded(email_address="john.doe@gmail.com", name="John Doe")
        )


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
