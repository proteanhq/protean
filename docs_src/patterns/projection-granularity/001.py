# --8<-- [start:model]
from datetime import UTC, datetime

from protean import Domain, handle
from protean.exceptions import ObjectNotFoundError
from protean.fields import (
    Boolean,
    DateTime,
    Float,
    Identifier,
    Integer,
    List,
    String,
    Text,
)
from protean.utils.globals import current_domain

domain = Domain(name="Shop")


@domain.aggregate
class Customer:
    name: String(required=True)
    email: String(required=True)

    def rename(self, new_name: str) -> None:
        self.name = new_name
        self.raise_(CustomerNameChanged(customer_id=self.id, new_name=new_name))


@domain.event(part_of=Customer)
class CustomerNameChanged:
    customer_id: Identifier(required=True)
    new_name: String(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    warehouse_id: Identifier(required=True)
    status: String(default="draft")
    total: Float(default=0.0)

    def place(self, customer: Customer, items: list[str]) -> None:
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_id=customer.id,
                customer_name=customer.name,
                customer_email=customer.email,
                warehouse_id=self.warehouse_id,
                total=self.total,
                items=items,
                placed_at=datetime.now(UTC),
            )
        )

    def ship(self, tracking_number: str) -> None:
        self.status = "shipped"
        self.raise_(
            OrderShipped(
                order_id=self.id,
                warehouse_id=self.warehouse_id,
                tracking_number=tracking_number,
                shipped_at=datetime.now(UTC),
            )
        )

    def deliver(self) -> None:
        self.status = "delivered"
        self.raise_(OrderDelivered(order_id=self.id, warehouse_id=self.warehouse_id))


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String()
    customer_email: String()
    warehouse_id: Identifier(required=True)
    total: Float()
    items: List(content_type=String)
    placed_at: DateTime()


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    warehouse_id: Identifier(required=True)
    tracking_number: String()
    shipped_at: DateTime()


@domain.event(part_of=Order)
class OrderDelivered:
    order_id: Identifier(required=True)
    warehouse_id: Identifier(required=True)


# --8<-- [end:model]


# --8<-- [start:order_summary]
@domain.projection
class OrderSummary:
    """Serves the order list page and the order detail page.

    Combines data from the Order and Customer aggregates
    into a single denormalized read model.
    """

    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    customer_name: String()
    customer_email: String()
    status: String()
    total: Float()
    item_count: Integer()
    placed_at: DateTime()
    shipped_at: DateTime()
    tracking_number: String()


# --8<-- [end:order_summary]


# --8<-- [start:order_summary_projector]
@domain.projector(
    projector_for=OrderSummary,
    stream_categories=[
        Order.meta_.stream_category,  # "shop::order"
        Customer.meta_.stream_category,  # "shop::customer"
    ],
)
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(
            OrderSummary(
                order_id=event.order_id,
                customer_id=event.customer_id,
                customer_name=event.customer_name,
                customer_email=event.customer_email,
                status="placed",
                total=event.total,
                item_count=len(event.items),
                placed_at=event.placed_at,
            )
        )

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped) -> None:
        repo = current_domain.repository_for(OrderSummary)
        summary = repo.get(event.order_id)
        summary.status = "shipped"
        summary.shipped_at = event.shipped_at
        summary.tracking_number = event.tracking_number
        repo.add(summary)

    @handle(CustomerNameChanged)
    def on_customer_name_changed(self, event: CustomerNameChanged) -> None:
        """Update all orders for this customer when their name changes."""
        view = current_domain.view_for(OrderSummary)
        # A query stops at 100 records unless the limit is lifted
        results = view.query.filter(customer_id=event.customer_id).limit(None).all()
        repo = current_domain.repository_for(OrderSummary)
        for order in results.items:
            order.customer_name = event.new_name
            repo.add(order)


# --8<-- [end:order_summary_projector]


# --8<-- [start:dashboard]
@domain.projection(cache="default")
class WarehouseDashboard:
    """Real-time order status counts for the warehouse display.

    Cache-backed because:
    - Looked up by a single key (warehouse_id)
    - Updates frequently (every order status change)
    - Never queried with filters or sorting
    - Acceptable to lose on cache eviction: a rebuild from events restores
      it, and until then shipping or delivering an order for that warehouse
      fails with ObjectNotFoundError
    """

    warehouse_id: Identifier(identifier=True)
    pending_count: Integer(default=0)
    shipped_count: Integer(default=0)
    delivered_count: Integer(default=0)
    last_updated: DateTime()


# --8<-- [end:dashboard]


# --8<-- [start:dashboard_projector]
@domain.projector(projector_for=WarehouseDashboard, aggregates=[Order])
class WarehouseDashboardProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        try:
            dashboard = current_domain.view_for(WarehouseDashboard).get(
                event.warehouse_id
            )
        except ObjectNotFoundError:
            dashboard = WarehouseDashboard(warehouse_id=event.warehouse_id)
        dashboard.pending_count += 1
        dashboard.last_updated = datetime.now(UTC)
        current_domain.cache_for(WarehouseDashboard).add(dashboard)

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped) -> None:
        view = current_domain.view_for(WarehouseDashboard)
        dashboard = view.get(event.warehouse_id)
        dashboard.pending_count -= 1
        dashboard.shipped_count += 1
        dashboard.last_updated = datetime.now(UTC)
        current_domain.cache_for(WarehouseDashboard).add(dashboard)

    @handle(OrderDelivered)
    def on_order_delivered(self, event: OrderDelivered) -> None:
        view = current_domain.view_for(WarehouseDashboard)
        dashboard = view.get(event.warehouse_id)
        dashboard.shipped_count -= 1
        dashboard.delivered_count += 1
        dashboard.last_updated = datetime.now(UTC)
        current_domain.cache_for(WarehouseDashboard).add(dashboard)


# --8<-- [end:dashboard_projector]


# --8<-- [start:dashboard_read]
def warehouse_dashboard(warehouse_id: str) -> WarehouseDashboard:
    view = domain.view_for(WarehouseDashboard)
    return view.get(warehouse_id)


# --8<-- [end:dashboard_read]


# --8<-- [start:order_history]
@domain.projection(provider="default")
class OrderHistory:
    """Searchable order history for customer service.

    Database-backed because it needs filtering, ordering, and pagination.
    """

    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    customer_name: String()
    status: String()
    total: Float()
    placed_at: DateTime()
    shipped_at: DateTime()
    cancelled_at: DateTime()
    cancellation_reason: String()


# --8<-- [end:order_history]


# --8<-- [start:order_history_queries]
def customer_orders(customer_id: str):
    """All orders for a customer, newest first."""
    view = domain.view_for(OrderHistory)
    return (
        view.query.filter(customer_id=customer_id)
        .order_by("-placed_at")
        .limit(None)
        .all()
    )


def cancelled_between(start_date: datetime, end_date: datetime):
    """Cancelled orders in a date range."""
    view = domain.view_for(OrderHistory)
    return (
        view.query.filter(status="cancelled")
        .filter(cancelled_at__gte=start_date)
        .filter(cancelled_at__lte=end_date)
        .all()
    )


def pending_count() -> int:
    view = domain.view_for(OrderHistory)
    return view.query.filter(status="placed").all().total


# --8<-- [end:order_history_queries]


# --8<-- [start:order_view]
@domain.projection
class OrderView:
    """Serves both the order list and order detail endpoints.

    The list endpoint returns: order_id, customer_name, status, total, placed_at
    The detail endpoint returns: all fields

    One projection, two serializers in the API layer.
    """

    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    customer_name: String()
    customer_email: String()
    status: String()
    total: Float()
    item_count: Integer()
    placed_at: DateTime()
    # Detail-only fields (optional, populated when available)
    shipped_at: DateTime()
    delivered_at: DateTime()
    tracking_number: String()
    cancellation_reason: String()


# --8<-- [end:order_view]


# --8<-- [start:order_view_api]
def get_orders():
    """GET /orders -- list view, subset of fields."""
    view = domain.view_for(OrderView)
    orders = view.query.order_by("-placed_at").limit(50).all()
    return [
        {
            "order_id": o.order_id,
            "customer_name": o.customer_name,
            "status": o.status,
            "total": o.total,
            "placed_at": o.placed_at,
        }
        for o in orders
    ]


def get_order(order_id: str):
    """GET /orders/{id} -- detail view, all fields."""
    view = domain.view_for(OrderView)
    order = view.get(order_id)
    return order.to_dict()


# --8<-- [end:order_view_api]


# --8<-- [start:product]
# No projection needed -- the aggregate is the read model
@domain.aggregate
class Product:
    name: String(required=True)
    description: Text()
    price: Float(required=True)
    category: String()
    is_active: Boolean(default=True)


def product_detail(product_id: str) -> Product:
    # The product detail page needs exactly these fields.
    # No cross-aggregate data, no denormalization needed.
    # Query the aggregate repository directly.
    repo = domain.repository_for(Product)
    return repo.get(product_id)


# --8<-- [end:product]

domain.init(traverse=False)
