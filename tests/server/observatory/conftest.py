import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain(request):
    if "no_test_domain" in request.keywords:
        yield
    else:
        domain = initialize_domain(name="Observatory Tests", root_path=__file__)
        domain.init(traverse=False)

        with domain.domain_context():
            yield domain


# ---------------------------------------------------------------------------
# Shared multi-aggregate domain fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_agg_domain():
    """Domain with multiple aggregates for cross-aggregate edge testing."""
    from protean import Domain
    from protean.core.aggregate import BaseAggregate
    from protean.core.command import BaseCommand
    from protean.core.command_handler import BaseCommandHandler
    from protean.core.event import BaseEvent
    from protean.core.event_handler import BaseEventHandler
    from protean.fields import Identifier, String
    from protean.utils.mixins import handle

    domain = Domain(name="MultiAgg")

    @domain.aggregate
    class Order(BaseAggregate):
        customer_id = Identifier(required=True)
        status = String(default="draft")

        def place(self):
            self.raise_(OrderPlaced(order_id=self.id, customer_id=self.customer_id))

    @domain.event(part_of=Order)
    class OrderPlaced(BaseEvent):
        order_id = Identifier(required=True)
        customer_id = Identifier(required=True)

    @domain.command(part_of=Order)
    class PlaceOrder(BaseCommand):
        order_id = Identifier(required=True)
        customer_id = Identifier(required=True)

    @domain.command_handler(part_of=Order)
    class OrderCommandHandler(BaseCommandHandler):
        @handle(PlaceOrder)
        def handle_place_order(self, command):
            pass

    @domain.aggregate
    class Inventory(BaseAggregate):
        sku = String(required=True)
        quantity = String(default="0")

    @domain.event_handler(part_of=Inventory, stream_category="order")
    class InventoryOrderHandler(BaseEventHandler):
        @handle(OrderPlaced)
        def on_order_placed(self, event):
            pass

    domain.init(traverse=False)
    return domain


@pytest.fixture
def multi_agg_observatory(multi_agg_domain):
    return Observatory(domains=[multi_agg_domain])


@pytest.fixture
def multi_agg_client(multi_agg_observatory):
    return TestClient(multi_agg_observatory.app)
