"""Tests for TypeManager — the extracted event/command type management logic.

These tests exercise the TypeManager methods through the Domain's ``init()``
pipeline (the same way they run in production) to verify that type strings
are assigned, external events are registered, and fact event classes are
generated correctly.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, String


# --- Shared fixtures ---------------------------------------------------------


class Account(BaseAggregate):
    name: String(required=True)


class CreateAccount(BaseCommand):
    name: String(required=True)


class AccountCreated(BaseEvent):
    name: String(required=True)


# --- set_and_record_types() --------------------------------------------------


class TestSetAndRecordTypes:
    """Verify that __type__ is set on events and commands with the correct format."""

    def test_event_type_is_set(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.init(traverse=False)

        assert hasattr(AccountCreated, "__type__")
        assert AccountCreated.__type__ == "Test.AccountCreated.v1"

    def test_command_type_is_set(self, test_domain):
        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.init(traverse=False)

        assert hasattr(CreateAccount, "__type__")
        assert CreateAccount.__type__ == "Test.CreateAccount.v1"

    def test_type_format_is_domain_class_version(self, test_domain):
        """Type string follows DomainName.ClassName.version format."""
        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.init(traverse=False)

        for cls in [AccountCreated, CreateAccount]:
            parts = cls.__type__.split(".")
            assert len(parts) == 3
            assert parts[0] == "Test"
            assert parts[1] == cls.__name__
            assert parts[2] == cls.__version__

    def test_typed_events_are_recorded_in_events_and_commands(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.init(traverse=False)

        registry = test_domain._events_and_commands
        assert "Test.AccountCreated.v1" in registry
        assert registry["Test.AccountCreated.v1"] is AccountCreated
        assert "Test.CreateAccount.v1" in registry
        assert registry["Test.CreateAccount.v1"] is CreateAccount

    def test_versioned_event_type_string(self, test_domain):
        """An event with a custom version uses that version in the type string."""

        class V2Event(BaseEvent):
            __version__ = "v2"
            value: String()

        test_domain.register(Account)
        test_domain.register(V2Event, part_of=Account)
        test_domain.init(traverse=False)

        assert V2Event.__type__ == "Test.V2Event.v2"

    def test_multiple_events_and_commands_all_recorded(self, test_domain):
        """All registered events and commands appear in the type registry."""

        class DeactivateAccount(BaseCommand):
            account_id: String(required=True)

        class AccountDeactivated(BaseEvent):
            account_id: String(required=True)

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(AccountDeactivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(DeactivateAccount, part_of=Account)
        test_domain.init(traverse=False)

        registry = test_domain._events_and_commands
        assert len(registry) >= 4
        assert "Test.AccountCreated.v1" in registry
        assert "Test.AccountDeactivated.v1" in registry
        assert "Test.CreateAccount.v1" in registry
        assert "Test.DeactivateAccount.v1" in registry


# --- register_external_event() -----------------------------------------------


class TestRegisterExternalEvent:
    """Verify registration of external events with custom type strings."""

    def test_external_event_is_registered(self, test_domain):
        class ExternalEvent(BaseEvent):
            data: String()

        test_domain.register_external_event(
            ExternalEvent, "OtherDomain.ExternalEvent.v1"
        )

        assert "OtherDomain.ExternalEvent.v1" in test_domain._events_and_commands
        assert (
            test_domain._events_and_commands["OtherDomain.ExternalEvent.v1"]
            is ExternalEvent
        )

    def test_external_event_type_string_is_set_on_class(self, test_domain):
        class ExternalEvent(BaseEvent):
            data: String()

        test_domain.register_external_event(ExternalEvent, "Billing.PaymentReceived.v1")

        assert ExternalEvent.__type__ == "Billing.PaymentReceived.v1"

    def test_external_event_not_in_domain_registry(self, test_domain):
        """External events are NOT added to the domain registry, only to the type map."""

        class ExternalEvent(BaseEvent):
            data: String()

        test_domain.register_external_event(ExternalEvent, "Ext.ExternalEvent.v1")

        assert "Ext.ExternalEvent.v1" in test_domain._events_and_commands
        # The event should not appear in the domain's element registry
        from protean.utils import fully_qualified_name

        assert fully_qualified_name(ExternalEvent) not in test_domain.registry.events

    def test_registering_non_event_class_raises_error(self, test_domain):
        class NotAnEvent:
            pass

        with pytest.raises(IncorrectUsageError, match="is not an Event"):
            test_domain.register_external_event(NotAnEvent, "Foo.NotAnEvent.v1")

    def test_registering_command_as_external_event_raises_error(self, test_domain):
        """Commands should not be accepted by register_external_event."""

        class SomeCommand(BaseCommand):
            value: String()

        with pytest.raises(IncorrectUsageError, match="is not an Event"):
            test_domain.register_external_event(SomeCommand, "Foo.SomeCommand.v1")


# --- generate_fact_event_classes() --------------------------------------------


class TestGenerateFactEventClasses:
    """Verify fact event class generation for aggregates with fact_events enabled."""

    def test_fact_event_generated_for_aggregate(self, test_domain):
        class Order(BaseAggregate):
            item: String(required=True)

        test_domain.register(Order, fact_events=True)
        test_domain.init(traverse=False)

        # The fact event class should be registered in the domain
        fact_event_name = "OrderFactEvent"
        # Find the fact event class in the events registry (values are DomainRecord)
        fact_records = [
            record
            for name, record in test_domain.registry.events.items()
            if fact_event_name in name
        ]
        assert len(fact_records) == 1
        assert issubclass(fact_records[0].cls, BaseEvent)

    def test_fact_event_not_generated_when_disabled(self, test_domain):
        """Aggregates without fact_events=True should not get fact event classes."""

        class SimpleAggregate(BaseAggregate):
            value: String()

        test_domain.register(SimpleAggregate)
        test_domain.init(traverse=False)

        fact_records = [
            record
            for name, record in test_domain.registry.events.items()
            if "SimpleAggregateFactEvent" in name
        ]
        assert len(fact_records) == 0

    def test_fact_event_has_aggregate_fields(self, test_domain):
        """Generated fact event should include the aggregate's fields."""
        from protean.core.aggregate import element_to_fact_event

        class Product(BaseAggregate):
            name: String(required=True)
            sku: String(required=True)

        test_domain.register(Product, fact_events=True)
        test_domain.init(traverse=False)

        # Use element_to_fact_event directly to inspect fields, since the
        # registry stores DomainRecord wrappers.
        fact_cls = element_to_fact_event(Product)
        from protean.utils.reflection import declared_fields

        fact_fields = declared_fields(fact_cls)
        assert "name" in fact_fields
        assert "sku" in fact_fields

    def test_fact_event_receives_type_string(self, test_domain):
        """Generated fact event classes should get __type__ set via set_and_record_types."""

        class Shipment(BaseAggregate):
            tracking_number: String()

        test_domain.register(Shipment, fact_events=True)
        test_domain.init(traverse=False)

        fact_records = [
            record
            for name, record in test_domain.registry.events.items()
            if "ShipmentFactEvent" in name
        ]
        assert len(fact_records) == 1
        fact_cls = fact_records[0].cls
        assert hasattr(fact_cls, "__type__")
        assert "ShipmentFactEvent" in fact_cls.__type__


# --- Property proxies on Domain ----------------------------------------------


class TestPropertyProxies:
    """Verify that Domain property proxies delegate to the TypeManager."""

    def test_events_and_commands_proxy(self, test_domain):
        """domain._events_and_commands returns the TypeManager's dict."""
        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.init(traverse=False)

        proxy_result = test_domain._events_and_commands
        internal_result = test_domain._type_manager.events_and_commands

        assert proxy_result is internal_result

    def test_upcasters_proxy(self, test_domain):
        """domain._upcasters returns the TypeManager's list."""
        proxy_result = test_domain._upcasters
        internal_result = test_domain._type_manager.upcasters

        assert proxy_result is internal_result

    def test_upcaster_chain_proxy(self, test_domain):
        """domain._upcaster_chain returns the TypeManager's chain."""
        proxy_result = test_domain._upcaster_chain
        internal_result = test_domain._type_manager.upcaster_chain

        assert proxy_result is internal_result


# --- Domain name in type string -----------------------------------------------


class TestDomainNameInTypeString:
    """Verify that the domain's camel-case name is used in type strings."""

    @pytest.mark.no_test_domain
    def test_custom_domain_name_in_type_string(self):
        """Type strings use the domain's CamelCase name, not a fixed prefix."""
        from protean.domain import Domain

        domain = Domain(name="my_billing")

        class Invoice(BaseAggregate):
            amount: Integer()

        class InvoiceCreated(BaseEvent):
            amount: Integer()

        domain.register(Invoice)
        domain.register(InvoiceCreated, part_of=Invoice)
        domain.init(traverse=False)

        assert InvoiceCreated.__type__ == "MyBilling.InvoiceCreated.v1"

    @pytest.mark.no_test_domain
    def test_hyphenated_domain_name_is_camel_cased(self):
        """Hyphens in domain names are converted to CamelCase."""
        from protean.domain import Domain

        domain = Domain(name="order-management")

        class Ticket(BaseAggregate):
            title: String()

        class TicketOpened(BaseEvent):
            title: String()

        domain.register(Ticket)
        domain.register(TicketOpened, part_of=Ticket)
        domain.init(traverse=False)

        assert TicketOpened.__type__.startswith("OrderManagement.")
