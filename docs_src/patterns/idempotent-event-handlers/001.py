from protean import Domain, handle

# --8<-- [start:upsert_imports]
from protean.exceptions import ObjectNotFoundError

# --8<-- [end:upsert_imports]
from protean.fields import (
    Auto,
    DateTime,
    Dict,
    Float,
    Identifier,
    Integer,
    List,
    String,
)
from protean.utils.globals import current_domain

domain = Domain(name="IdempotentHandlers")


# --8<-- [start:order]
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    customer_name: String()
    total: Float(required=True)
    items: List(content_type=Dict)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String()
    total: Float(required=True)
    items: List(content_type=Dict)
    placed_at: DateTime()


@domain.event(part_of=Order)
class OrderPaid:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    shipped_at: DateTime()
    tracking_number: String()


# --8<-- [end:order]


# --8<-- [start:set_based]
@domain.aggregate
class OrderStatus:
    order_id: Identifier(identifier=True)
    status: String(default="placed")
    shipped_at: DateTime()
    tracking_number: String()


@domain.event_handler(part_of=Order)
class OrderStatusEventHandler:
    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderStatus)
        status = repo.get(event.order_id)
        # Setting status to "shipped" is idempotent.
        # Doing it twice produces the same result.
        status.status = "shipped"
        status.shipped_at = event.shipped_at
        status.tracking_number = event.tracking_number
        repo.add(status)


# --8<-- [end:set_based]


# --8<-- [start:order_stats]
@domain.aggregate
class OrderStats:
    stats_id: Identifier(identifier=True)
    order_totals: Dict()
    order_count: Integer(default=0)
    total_revenue: Float(default=0.0)

    def record_order(self, order_id: str, total: float) -> None:
        # Keyed by order ID: recording the same order twice is a no-op
        self.order_totals = {**self.order_totals, order_id: total}
        # Recalculate from the stored orders instead of adding to a running total
        self.order_count = len(self.order_totals)
        self.total_revenue = sum(self.order_totals.values())


@domain.event_handler(part_of=Order)
class OrderStatsEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderStats)
        stats = repo.get("all-orders")
        stats.record_order(event.order_id, event.total)
        repo.add(stats)


# --8<-- [end:order_stats]


# --8<-- [start:check_before_act]
@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    available_quantity: Integer(default=0)
    reserved_for_orders: List(content_type=String)

    def reserve(self, quantity: int, order_id: str) -> None:
        self.available_quantity -= quantity
        self.reserved_for_orders = [*self.reserved_for_orders, order_id]


@domain.event_handler(part_of=Order)
class InventoryEventHandler:
    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)

        # One reservation per product: an order can list a product twice
        quantities: dict[str, int] = {}
        for item in event.items:
            product_id = item["product_id"]
            quantities[product_id] = quantities.get(product_id, 0) + item["quantity"]

        for product_id, quantity in quantities.items():
            inventory = repo.get(product_id)

            # Check if this event's reservation was already applied
            if event.order_id in inventory.reserved_for_orders:
                continue  # Already processed, skip

            inventory.reserve(quantity=quantity, order_id=event.order_id)
            repo.add(inventory)


# --8<-- [end:check_before_act]


# --8<-- [start:processed_events]
@domain.aggregate
class CustomerLoyalty:
    customer_id: Identifier(identifier=True)
    points: Integer(default=0)
    processed_events: List(content_type=String)

    def add_points(self, amount: int) -> None:
        self.points += amount


@domain.event_handler(part_of=Order)
class LoyaltyEventHandler:
    @handle(OrderPlaced)
    def award_points(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)

        # Use the event's unique ID for deduplication
        event_id = event._metadata.headers.id
        if event_id in loyalty.processed_events:
            return  # Already processed

        loyalty.add_points(int(event.total))
        # Assign a new list: an in-place append is not tracked as a change
        loyalty.processed_events = [*loyalty.processed_events, event_id]
        repo.add(loyalty)


# --8<-- [end:processed_events]


# --8<-- [start:global_position]
@domain.aggregate
class ProjectionState:
    state_id: Identifier(identifier=True)
    order_count: Integer(default=0)
    total_revenue: Float(default=0.0)
    last_processed_position: Integer(default=-1)

    def apply_order_placed(self, event: OrderPlaced) -> None:
        self.order_count += 1
        self.total_revenue += event.total


@domain.event_handler(part_of=Order)
class ProjectionStateHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(ProjectionState)
        state = repo.get("order-projection")

        # Use the store-wide global position for deduplication
        event_position = event._metadata.event_store.global_position
        if event_position <= state.last_processed_position:
            return  # Already processed or older

        # Process the event
        state.apply_order_placed(event)
        state.last_processed_position = event_position
        repo.add(state)


# --8<-- [end:global_position]


# --8<-- [start:upsert]
@domain.projection
class OrderSummaryProjection:
    order_id: Identifier(identifier=True)
    customer_name: String()
    status: String()
    total: Float()
    placed_at: DateTime()


@domain.projector(projector_for=OrderSummaryProjection, aggregates=[Order])
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderSummaryProjection)

        # Check if the projection already exists
        try:
            existing = repo.get(event.order_id)
        except ObjectNotFoundError:
            existing = None

        if existing:
            # Already created: update instead of insert
            existing.customer_name = event.customer_name
            existing.total = event.total
            existing.placed_at = event.placed_at
            existing.status = "placed"
            repo.add(existing)
        else:
            # First time: create
            projection = OrderSummaryProjection(
                order_id=event.order_id,
                customer_name=event.customer_name,
                status="placed",
                total=event.total,
                placed_at=event.placed_at,
            )
            repo.add(projection)


# --8<-- [end:upsert]


# --8<-- [start:existence_guard]
@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)
    status: String(default="pending")


@domain.repository(part_of=Shipment)
class ShipmentRepository:
    def find_by_order_id(self, order_id: str) -> Shipment | None:
        return self.query.filter(order_id=order_id).first


@domain.event_handler(part_of=Order)
class ShipmentEventHandler:
    @handle(OrderPaid)
    def create_shipment(self, event: OrderPaid):
        repo = current_domain.repository_for(Shipment)

        # Check if a shipment already exists for this order
        existing = repo.find_by_order_id(event.order_id)
        if existing:
            return  # Shipment already created

        shipment = Shipment(
            order_id=event.order_id,
            customer_id=event.customer_id,
            items=event.items,
            status="pending",
        )
        repo.add(shipment)


# --8<-- [end:existence_guard]


# --8<-- [start:dashboard]
@domain.projection
class OrderDashboardProjection:
    order_id: Identifier(identifier=True)
    customer_name: String()
    status: String()
    total: Float()
    placed_at: DateTime()
    shipped_at: DateTime()


@domain.projector(projector_for=OrderDashboardProjection, aggregates=[Order])
class OrderDashboardProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboardProjection)
        # Upsert pattern: create or update
        try:
            projection = repo.get(event.order_id)
        except ObjectNotFoundError:
            projection = OrderDashboardProjection(order_id=event.order_id)

        projection.customer_name = event.customer_name
        projection.status = "placed"
        projection.total = event.total
        projection.placed_at = event.placed_at
        repo.add(projection)

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderDashboardProjection)
        try:
            projection = repo.get(event.order_id)
        except ObjectNotFoundError:
            return  # The order was never projected, so there is nothing to ship
        projection.status = "shipped"
        projection.shipped_at = event.shipped_at
        repo.add(projection)


# --8<-- [end:dashboard]


# --8<-- [start:account]
@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    balance: Float(default=0.0)
    processed_transfers: List(content_type=String)

    def credit(self, amount: float) -> None:
        self.balance += amount


@domain.event(part_of=Account)
class MoneyDebited:
    account_id: Identifier(required=True)
    target_account_id: Identifier(required=True)
    transfer_id: Identifier(required=True)
    amount: Float(required=True)


@domain.event_handler(part_of=Account)
class AccountEventHandler:
    @handle(MoneyDebited)
    def credit_target(self, event: MoneyDebited):
        repo = current_domain.repository_for(Account)
        target = repo.get(event.target_account_id)

        # Must deduplicate because credit is additive
        if event.transfer_id in target.processed_transfers:
            return

        target.credit(event.amount)
        target.processed_transfers = [*target.processed_transfers, event.transfer_id]
        repo.add(target)


# --8<-- [end:account]
