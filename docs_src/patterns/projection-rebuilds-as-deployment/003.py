from protean import Domain, handle
from protean.exceptions import ObjectNotFoundError
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    subtotal: Float(default=0.0)
    tax: Float(default=0.0)
    shipping: Float(default=0.0)
    status: String(max_length=20, default="draft")

    def place(self) -> None:
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_name=self.customer_name,
                subtotal=self.subtotal,
                tax=self.tax,
                shipping=self.shipping,
            )
        )

    def ship(self) -> None:
        self.status = "shipped"
        self.raise_(OrderShipped(order_id=self.id))


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_name: String(max_length=100)
    subtotal: Float()
    tax: Float()
    shipping: Float()


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)


# --8<-- [start:blue_green]
# The existing projection -- still serving traffic
@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    customer_name: String(max_length=100)
    total: Float()
    status: String(max_length=20)


# The new projection -- different schema_name, same data
@domain.projection(schema_name="order_summary_v2")
class OrderSummaryV2:
    order_id: Identifier(identifier=True)
    customer_name: String(max_length=100)
    subtotal: Float()
    tax: Float()
    shipping: Float()
    total: Float()
    status: String(max_length=20)


# --8<-- [end:blue_green]


@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderSummary)
        repo.add(
            OrderSummary(
                order_id=event.order_id,
                customer_name=event.customer_name,
                total=event.subtotal + event.tax + event.shipping,
                status="placed",
            )
        )

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderSummary)
        summary = repo.get(event.order_id)
        summary.status = "shipped"
        repo.add(summary)


# --8<-- [start:v2_projector]
@domain.projector(projector_for=OrderSummaryV2, aggregates=[Order])
class OrderSummaryV2Projector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderSummaryV2)
        # A rebuild may already hold this row: the new projector's first Engine
        # run starts at the beginning of the event store and replays it
        try:
            repo.get(event.order_id)
            return
        except ObjectNotFoundError:
            pass
        repo.add(
            OrderSummaryV2(
                order_id=event.order_id,
                customer_name=event.customer_name,
                subtotal=event.subtotal,
                tax=event.tax,
                shipping=event.shipping,
                total=event.subtotal + event.tax + event.shipping,
                status="placed",
            )
        )

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderSummaryV2)
        summary = repo.get(event.order_id)
        summary.status = "shipped"
        repo.add(summary)


# --8<-- [end:v2_projector]


# --8<-- [start:rebuild_v2]
def rebuild_v2():
    with domain.domain_context():
        result = domain.rebuild_projection(OrderSummaryV2)

        if result.success:
            print(
                f"OrderSummaryV2 rebuilt: {result.events_dispatched} events processed"
            )
        else:
            print(f"Rebuild failed: {result.errors}")
    return result


# --8<-- [end:rebuild_v2]


# --8<-- [start:api_before]
from fastapi import FastAPI

app = FastAPI()


# Before: reading from the old projection
@app.get("/orders/{order_id}/summary")
def get_order_summary(order_id: str):
    return domain.view_for(OrderSummary).get(order_id).to_dict()


# --8<-- [end:api_before]


# --8<-- [start:api_after]
app = FastAPI()


# After: reading from the new projection
@app.get("/orders/{order_id}/summary")
def get_order_summary_v2(order_id: str):
    return domain.view_for(OrderSummaryV2).get(order_id).to_dict()


# --8<-- [end:api_after]


# --8<-- [start:monitor]
from protean.utils.projection_rebuilder import RebuildResult


def rebuild_and_report() -> RebuildResult:
    with domain.domain_context():
        result: RebuildResult = domain.rebuild_projection(OrderSummaryV2)

        # Basic outcome
        print(f"Projection:   {result.projection_name}")
        print(f"Success:      {result.success}")

        # Volume stats
        print(f"Dispatched:   {result.events_dispatched}")
        print(f"Skipped:      {result.events_skipped}")

        # Infrastructure stats
        print(f"Projectors:   {result.projectors_processed}")
        print(f"Categories:   {result.categories_processed}")

        # Errors (empty list on success)
        if result.errors:
            for error in result.errors:
                print(f"  ERROR: {error}")
    return result


# --8<-- [end:monitor]

domain.init(traverse=False)
