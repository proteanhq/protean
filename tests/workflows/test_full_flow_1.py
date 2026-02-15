"""End-to-end vertical slice exercising the full command flow with
Pydantic-native field definitions.

Tests the complete path:
  Command → CommandHandler → Aggregate (mutation + event) → EventHandler → Projection

All domain elements use the new annotation-style or raw Pydantic field
definitions (not legacy assignment style) to verify the Pydantic migration
works end-to-end.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.domain import Domain
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements: mixing annotation-style and raw Pydantic styles
# ---------------------------------------------------------------------------


class Money(BaseValueObject):
    """Value object using annotation-style fields."""

    amount: Float(min_value=0, required=True)
    currency: String(max_length=3, default="USD")


class LineItem(BaseEntity):
    """Entity using annotation-style fields with assignment-style descriptors."""

    product_name: String(max_length=200, required=True)
    unit_price = ValueObject(Money)
    quantity: Integer(min_value=1, required=True)


class Invoice(BaseAggregate):
    """Aggregate using annotation-style fields with assignment-style descriptors."""

    customer_name: String(max_length=200, required=True)
    items = HasMany(LineItem)
    status: String(choices=["DRAFT", "SENT", "PAID", "CANCELLED"], default="DRAFT")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Commands


class CreateInvoice(BaseCommand):
    """Command using annotation-style fields."""

    invoice_id: Identifier(identifier=True)
    customer_name: String(max_length=200, required=True)


class AddLineItem(BaseCommand):
    """Command using annotation-style fields."""

    invoice_id: Identifier(required=True)
    product_name: String(max_length=200, required=True)
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")
    quantity: Integer(min_value=1, required=True)


class SendInvoice(BaseCommand):
    """Command using annotation-style fields."""

    invoice_id: Identifier(required=True)


# Events


class InvoiceCreated(BaseEvent):
    """Event using annotation-style fields."""

    invoice_id: Identifier(identifier=True)
    customer_name: String(max_length=200, required=True)


class LineItemAdded(BaseEvent):
    """Event using annotation-style fields."""

    invoice_id: Identifier(identifier=True)
    product_name: String(max_length=200, required=True)
    amount: Float(required=True)
    currency: String(max_length=3, required=True)
    quantity: Integer(required=True)


class InvoiceSent(BaseEvent):
    """Event using annotation-style fields."""

    invoice_id: Identifier(identifier=True)
    customer_name: String(max_length=200, required=True)


# Command Handlers


class InvoiceCommandHandler(BaseCommandHandler):
    @handle(CreateInvoice)
    def create_invoice(self, command: CreateInvoice) -> None:
        invoice = Invoice(
            id=command.invoice_id,
            customer_name=command.customer_name,
        )
        invoice.raise_(
            InvoiceCreated(
                invoice_id=invoice.id,
                customer_name=invoice.customer_name,
            )
        )
        current_domain.repository_for(Invoice).add(invoice)

    @handle(AddLineItem)
    def add_line_item(self, command: AddLineItem) -> None:
        invoice = current_domain.repository_for(Invoice).get(command.invoice_id)
        item = LineItem(
            product_name=command.product_name,
            unit_price=Money(amount=command.amount, currency=command.currency),
            quantity=command.quantity,
        )
        invoice.add_items(item)
        invoice.raise_(
            LineItemAdded(
                invoice_id=invoice.id,
                product_name=command.product_name,
                amount=command.amount,
                currency=command.currency,
                quantity=command.quantity,
            )
        )
        current_domain.repository_for(Invoice).add(invoice)

    @handle(SendInvoice)
    def send_invoice(self, command: SendInvoice) -> None:
        invoice = current_domain.repository_for(Invoice).get(command.invoice_id)
        invoice.status = "SENT"
        invoice.raise_(
            InvoiceSent(
                invoice_id=invoice.id,
                customer_name=invoice.customer_name,
            )
        )
        current_domain.repository_for(Invoice).add(invoice)


# Projection (read model)


class InvoiceSummary(BaseProjection):
    """Projection using annotation-style fields."""

    invoice_id: Identifier(identifier=True)
    customer_name: String(max_length=200, required=True)
    line_item_count: Integer(default=0)
    status: String(max_length=20, default="DRAFT")


# Event Handler (updates the projection)


class InvoiceSummaryEventHandler(BaseEventHandler):
    @handle(InvoiceCreated)
    def on_invoice_created(self, event: InvoiceCreated) -> None:
        summary = InvoiceSummary(
            invoice_id=event.invoice_id,
            customer_name=event.customer_name,
            line_item_count=0,
            status="DRAFT",
        )
        current_domain.repository_for(InvoiceSummary).add(summary)

    @handle(LineItemAdded)
    def on_line_item_added(self, event: LineItemAdded) -> None:
        summary = current_domain.repository_for(InvoiceSummary).get(event.invoice_id)
        summary.line_item_count += 1
        current_domain.repository_for(InvoiceSummary).add(summary)

    @handle(InvoiceSent)
    def on_invoice_sent(self, event: InvoiceSent) -> None:
        summary = current_domain.repository_for(InvoiceSummary).get(event.invoice_id)
        summary.status = "SENT"
        current_domain.repository_for(InvoiceSummary).add(summary)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def invoice_domain():
    domain = Domain(name="InvoiceTest")

    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"

    domain.register(Invoice)
    domain.register(LineItem, part_of=Invoice)
    domain.register(CreateInvoice, part_of=Invoice)
    domain.register(AddLineItem, part_of=Invoice)
    domain.register(SendInvoice, part_of=Invoice)
    domain.register(InvoiceCreated, part_of=Invoice)
    domain.register(LineItemAdded, part_of=Invoice)
    domain.register(InvoiceSent, part_of=Invoice)
    domain.register(InvoiceCommandHandler, part_of=Invoice)
    domain.register(InvoiceSummary)
    domain.register(InvoiceSummaryEventHandler, part_of=Invoice)

    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEndToEndCommandFlow:
    """Tests the complete Command → Handler → Aggregate → Event → Handler → Projection flow."""

    def test_create_invoice_via_command(self, invoice_domain):
        invoice_id = str(uuid4())
        command = CreateInvoice(
            invoice_id=invoice_id,
            customer_name="Acme Corp",
        )
        invoice_domain.process(command)

        # Verify aggregate was persisted
        invoice = invoice_domain.repository_for(Invoice).get(invoice_id)
        assert invoice.customer_name == "Acme Corp"
        assert invoice.status == "DRAFT"

        # Verify projection was created by event handler
        summary = invoice_domain.repository_for(InvoiceSummary).get(invoice_id)
        assert summary.customer_name == "Acme Corp"
        assert summary.line_item_count == 0
        assert summary.status == "DRAFT"

    def test_add_line_items_via_commands(self, invoice_domain):
        invoice_id = str(uuid4())

        # Create invoice
        invoice_domain.process(
            CreateInvoice(invoice_id=invoice_id, customer_name="Acme Corp")
        )

        # Add two line items
        invoice_domain.process(
            AddLineItem(
                invoice_id=invoice_id,
                product_name="Widget A",
                amount=25.00,
                currency="USD",
                quantity=10,
            )
        )
        invoice_domain.process(
            AddLineItem(
                invoice_id=invoice_id,
                product_name="Widget B",
                amount=50.00,
                currency="EUR",
                quantity=5,
            )
        )

        # Verify aggregate has both items
        invoice = invoice_domain.repository_for(Invoice).get(invoice_id)
        assert len(invoice.items) == 2

        # Verify items have correct data including value object
        items_by_name = {item.product_name: item for item in invoice.items}
        assert items_by_name["Widget A"].unit_price.amount == 25.00
        assert items_by_name["Widget A"].unit_price.currency == "USD"
        assert items_by_name["Widget A"].quantity == 10
        assert items_by_name["Widget B"].unit_price.amount == 50.00
        assert items_by_name["Widget B"].unit_price.currency == "EUR"
        assert items_by_name["Widget B"].quantity == 5

        # Verify projection updated line item count
        summary = invoice_domain.repository_for(InvoiceSummary).get(invoice_id)
        assert summary.line_item_count == 2

    def test_send_invoice_updates_status(self, invoice_domain):
        invoice_id = str(uuid4())

        invoice_domain.process(
            CreateInvoice(invoice_id=invoice_id, customer_name="Acme Corp")
        )
        invoice_domain.process(SendInvoice(invoice_id=invoice_id))

        # Verify aggregate status
        invoice = invoice_domain.repository_for(Invoice).get(invoice_id)
        assert invoice.status == "SENT"

        # Verify projection status updated by event handler
        summary = invoice_domain.repository_for(InvoiceSummary).get(invoice_id)
        assert summary.status == "SENT"

    def test_full_lifecycle(self, invoice_domain):
        """Complete lifecycle: create → add items → send."""
        invoice_id = str(uuid4())

        # Create
        invoice_domain.process(
            CreateInvoice(invoice_id=invoice_id, customer_name="Test Customer")
        )

        # Add item
        invoice_domain.process(
            AddLineItem(
                invoice_id=invoice_id,
                product_name="Service Fee",
                amount=100.00,
                quantity=1,
            )
        )

        # Send
        invoice_domain.process(SendInvoice(invoice_id=invoice_id))

        # Verify final state
        invoice = invoice_domain.repository_for(Invoice).get(invoice_id)
        assert invoice.customer_name == "Test Customer"
        assert invoice.status == "SENT"
        assert len(invoice.items) == 1
        assert invoice.items[0].product_name == "Service Fee"
        assert invoice.items[0].unit_price.amount == 100.00
        assert invoice.items[0].unit_price.currency == "USD"

        summary = invoice_domain.repository_for(InvoiceSummary).get(invoice_id)
        assert summary.customer_name == "Test Customer"
        assert summary.line_item_count == 1
        assert summary.status == "SENT"


class TestValueObjectRoundTrip:
    """Tests that value objects survive the full persistence round-trip."""

    def test_vo_preserved_through_persistence(self, invoice_domain):
        invoice_id = str(uuid4())
        invoice_domain.process(
            CreateInvoice(invoice_id=invoice_id, customer_name="VO Test")
        )
        invoice_domain.process(
            AddLineItem(
                invoice_id=invoice_id,
                product_name="Premium Widget",
                amount=99.99,
                currency="GBP",
                quantity=3,
            )
        )

        # Load from repository (forces round-trip through memory adapter)
        invoice = invoice_domain.repository_for(Invoice).get(invoice_id)
        item = invoice.items[0]

        # Value object should be fully reconstructed
        assert isinstance(item.unit_price, Money)
        assert item.unit_price.amount == 99.99
        assert item.unit_price.currency == "GBP"

    def test_vo_in_to_dict(self, invoice_domain):
        invoice_id = str(uuid4())
        invoice_domain.process(
            CreateInvoice(invoice_id=invoice_id, customer_name="Dict Test")
        )
        invoice_domain.process(
            AddLineItem(
                invoice_id=invoice_id,
                product_name="Widget",
                amount=10.00,
                currency="USD",
                quantity=1,
            )
        )

        invoice = invoice_domain.repository_for(Invoice).get(invoice_id)
        data = invoice.to_dict()

        assert data["customer_name"] == "Dict Test"
        assert len(data["items"]) == 1
        assert data["items"][0]["product_name"] == "Widget"
        assert data["items"][0]["unit_price"]["amount"] == 10.00
        assert data["items"][0]["unit_price"]["currency"] == "USD"


class TestValidationInFlow:
    """Tests that validation works correctly through the command flow."""

    def test_command_validation_rejects_invalid_data(self, invoice_domain):
        with pytest.raises(ValidationError):
            CreateInvoice(
                invoice_id=str(uuid4()),
                customer_name="",  # Empty string for required field
            )

    def test_aggregate_field_validation_on_mutation(self, invoice_domain):
        invoice_id = str(uuid4())
        invoice_domain.process(
            CreateInvoice(invoice_id=invoice_id, customer_name="Valid Name")
        )
        invoice = invoice_domain.repository_for(Invoice).get(invoice_id)

        with pytest.raises(ValidationError):
            invoice.status = "INVALID_STATUS"  # Not in choices

    def test_vo_validation_rejects_negative_amount(self, invoice_domain):
        with pytest.raises(ValidationError):
            Money(amount=-5.00, currency="USD")

    def test_entity_validation_rejects_zero_quantity(self, invoice_domain):
        with pytest.raises(ValidationError):
            LineItem(
                product_name="Widget",
                unit_price=Money(amount=10.00),
                quantity=0,  # min_value=1
            )


class TestProjectionQueries:
    """Tests that projections are queryable after event handler updates."""

    def test_projection_not_found_before_creation(self, invoice_domain):
        with pytest.raises(ObjectNotFoundError):
            invoice_domain.repository_for(InvoiceSummary).get("nonexistent")

    def test_projection_reflects_aggregate_state(self, invoice_domain):
        invoice_id = str(uuid4())
        invoice_domain.process(
            CreateInvoice(invoice_id=invoice_id, customer_name="Query Test")
        )
        invoice_domain.process(
            AddLineItem(
                invoice_id=invoice_id,
                product_name="Item 1",
                amount=10.00,
                quantity=1,
            )
        )
        invoice_domain.process(
            AddLineItem(
                invoice_id=invoice_id,
                product_name="Item 2",
                amount=20.00,
                quantity=2,
            )
        )
        invoice_domain.process(SendInvoice(invoice_id=invoice_id))

        summary = invoice_domain.repository_for(InvoiceSummary).get(invoice_id)
        assert summary.invoice_id == invoice_id
        assert summary.customer_name == "Query Test"
        assert summary.line_item_count == 2
        assert summary.status == "SENT"
