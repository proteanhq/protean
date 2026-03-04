"""Shared test domain elements for IR builder tests."""

from protean import Domain, handle, invariant
from protean.core.aggregate import apply
from protean.fields import HasMany, HasOne, ValueObject as VOField

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


def build_extended_field_test_domain() -> Domain:
    """Build a domain with HasOne, Reference, callable defaults, descriptions."""
    domain = Domain(name="ExtFieldTest", root_path=".")

    @domain.entity(part_of="Catalog")
    class FeaturedItem:
        title = String(max_length=200, required=True)

    @domain.aggregate
    class Catalog:
        name = String(max_length=100, required=True, description="Catalog name")
        items_cache = List(content_type=str, default=lambda: [])
        featured = HasOne(FeaturedItem)

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


def build_es_aggregate_domain() -> Domain:
    """Build a domain with an event-sourced aggregate and @apply handlers."""
    domain = Domain(name="Banking", root_path=".")

    @domain.event(part_of="BankAccount")
    class AccountOpened:
        account_id = Identifier(required=True)
        holder_name = String(required=True)

    @domain.event(part_of="BankAccount")
    class DepositMade:
        account_id = Identifier(required=True)
        amount = Float(required=True)

    @domain.aggregate(is_event_sourced=True)
    class BankAccount:
        holder_name = String(max_length=100, required=True)
        balance = Float(default=0.0)

        @apply
        def opened(self, event: AccountOpened) -> None:
            self.holder_name = event.holder_name

        @apply
        def deposited(self, event: DepositMade) -> None:
            self.balance += event.amount

    domain.init(traverse=False)
    return domain


def build_domain_service_domain() -> Domain:
    """Build a domain with a domain service spanning multiple aggregates."""
    domain = Domain(name="Fulfillment", root_path=".")

    @domain.aggregate
    class Order:
        customer_name = String(max_length=100, required=True)
        total = Float(default=0.0)

    @domain.aggregate
    class Inventory:
        product_name = String(max_length=100, required=True)
        quantity = Integer(default=0)

    @domain.domain_service(part_of=[Order, Inventory])
    class PlaceOrderService:
        @invariant.pre
        def inventory_must_have_stock(self):
            pass

    domain.init(traverse=False)
    return domain


def build_process_manager_domain() -> Domain:
    """Build a domain with a process manager with start/end/correlate."""
    domain = Domain(name="OrderFlow", root_path=".")

    @domain.event(part_of="FlowOrder")
    class FlowOrderPlaced:
        order_id = Identifier(required=True)
        total = Float(required=True)

    @domain.event(part_of="FlowPayment")
    class FlowPaymentConfirmed:
        payment_id = Identifier(required=True)
        order_id = Identifier(required=True)

    @domain.event(part_of="FlowPayment")
    class FlowPaymentFailed:
        order_id = Identifier(required=True)
        reason = String()

    @domain.aggregate
    class FlowOrder:
        total = Float(default=0.0)

    @domain.aggregate
    class FlowPayment:
        order_id = Identifier()
        amount = Float()

    @domain.process_manager(stream_categories=["flow_order", "flow_payment"])
    class OrderFulfillment:
        order_id = Identifier()
        status = String(default="new")

        @handle(FlowOrderPlaced, start=True, correlate="order_id")
        def on_order_placed(self, event: FlowOrderPlaced) -> None:
            self.order_id = event.order_id
            self.status = "awaiting_payment"

        @handle(FlowPaymentConfirmed, correlate="order_id")
        def on_payment_confirmed(self, event: FlowPaymentConfirmed) -> None:
            self.status = "completed"
            self.mark_as_complete()

        @handle(FlowPaymentFailed, correlate="order_id", end=True)
        def on_payment_failed(self, event: FlowPaymentFailed) -> None:
            self.status = "cancelled"

    domain.init(traverse=False)
    return domain


def build_published_event_domain() -> Domain:
    """Build a domain with published events for contract testing.

    The ``published`` Meta option was added in a separate commit on main.
    We set the attribute manually here so this builder works regardless
    of whether the branch has been rebased onto that commit.
    """
    domain = Domain(name="PublishedTest", root_path=".")

    @domain.event(part_of="Account")
    class AccountCreated:
        account_id = Identifier(required=True)
        holder_name = String(required=True)

    @domain.event(part_of="Account")
    class AccountUpdated:
        account_id = Identifier(required=True)

    @domain.aggregate
    class Account:
        holder_name = String(max_length=100, required=True)

    domain.init(traverse=False)

    # Manually mark AccountCreated as published
    AccountCreated.meta_.published = True

    return domain
