"""Shared test domain elements for IR builder tests."""

from protean import Domain, handle, invariant
from protean.fields import HasMany, ValueObject as VOField

from protean.fields.containers import Dict, List
from protean.fields.simple import (
    Boolean,
    Date,
    DateTime,
    Float,
    Identifier,
    Integer,
    String,
    Text,
)


def build_field_test_domain() -> Domain:
    """Build a domain with diverse field types for field extraction tests."""
    domain = Domain(name="FieldTest", root_path=".")

    @domain.value_object
    class Address:
        street = String(max_length=255, required=True)
        city = String(max_length=100, required=True)
        zip_code = String(max_length=10, required=True)

    @domain.entity(part_of="Product")
    class Variant:
        name = String(max_length=100, required=True)
        sku = String(max_length=50)

    @domain.aggregate
    class Product:
        name = String(max_length=200, required=True, sanitize=True)
        description = Text()
        price = Float(min_value=0.0)
        quantity = Integer(min_value=0)
        is_active = Boolean(default=True)
        created_at = DateTime()
        launch_date = Date()
        sku = Identifier(required=True)
        tags = List(content_type=str)
        metadata_field = Dict()
        shipping_address = VOField(Address)
        variants = HasMany(Variant)
        status = String(max_length=20, choices=["ACTIVE", "INACTIVE", "ARCHIVED"])
        score = Float(default=0.0)

    domain.init(traverse=False)
    return domain


def build_cluster_test_domain() -> Domain:
    """Build a domain with aggregate, entity, value object, and invariants."""
    domain = Domain(name="ClusterTest", root_path=".")

    @domain.value_object
    class ShippingAddress:
        """A shipping address value object."""

        street = String(max_length=255, required=True)
        city = String(max_length=100, required=True)

    @domain.entity(part_of="Order")
    class LineItem:
        product_name = String(max_length=200, required=True)
        quantity = Integer(min_value=1, required=True)
        unit_price = Float(min_value=0.0, required=True)

    @domain.aggregate
    class Order:
        """An order aggregate with invariants."""

        customer_name = String(max_length=100, required=True)
        total = Float(min_value=0.0)
        shipping_address = VOField(ShippingAddress)
        items = HasMany(LineItem)

        @invariant.post
        def total_must_be_positive(self):
            if self.total is not None and self.total < 0:
                raise ValueError("Total must be positive")

    domain.init(traverse=False)
    return domain


def build_command_event_test_domain() -> Domain:
    """Build a domain with commands, events, and fact events."""
    domain = Domain(name="Ordering", root_path=".")

    @domain.command(part_of="Order")
    class PlaceOrder:
        customer_name = String(max_length=100, required=True)

    @domain.command(part_of="Order")
    class CancelOrder:
        order_id = Identifier(required=True)
        reason = String(max_length=500)

    @domain.event(part_of="Order")
    class OrderPlaced:
        order_id = Identifier(required=True)
        customer_name = String(required=True)
        total_amount = Float(required=True)

    @domain.event(part_of="Order")
    class OrderCancelled:
        order_id = Identifier(required=True)
        reason = String()

    @domain.aggregate(fact_events=True)
    class Order:
        customer_name = String(max_length=100, required=True)
        total = Float(min_value=0.0)

    domain.init(traverse=False)
    return domain


def build_handler_test_domain() -> Domain:
    """Build a domain with command handlers, event handlers, and services."""
    domain = Domain(name="HandlerTest", root_path=".")

    @domain.command(part_of="Account")
    class OpenAccount:
        holder_name = String(max_length=100, required=True)

    @domain.event(part_of="Account")
    class AccountOpened:
        account_id = Identifier(required=True)
        holder_name = String(required=True)

    @domain.aggregate
    class Account:
        holder_name = String(max_length=100, required=True)
        balance = Float(default=0.0)

    @domain.command_handler(part_of=Account)
    class AccountCommandHandler:
        @handle(OpenAccount)
        def handle_open_account(self, command):
            pass

    @domain.event_handler(part_of=Account)
    class AccountEventHandler:
        @handle(AccountOpened)
        def on_account_opened(self, event):
            pass

    @domain.application_service(part_of=Account)
    class AccountService:
        pass

    @domain.repository(part_of=Account)
    class AccountRepository:
        pass

    domain.init(traverse=False)
    return domain
