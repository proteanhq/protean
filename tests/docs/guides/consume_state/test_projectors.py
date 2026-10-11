"""Check what docs/guides/consume-state/projectors.md says projectors do.

Each test loads its example fresh, so every test gets its own domain, its own
memory store and its own memory event store. Most fixtures switch the domain
to synchronous event processing, so persisting an aggregate runs its
projectors before ``add()`` returns. The redelivery and ordering tests leave
processing asynchronous and hand the stored messages to the projector with
``_handle()``, the way the engine delivers them.
"""

import re
import subprocess
import sys

import pytest

from protean import Domain
from protean.core.projector import on
from protean.exceptions import (
    IncorrectUsageError,
    ObjectNotFoundError,
    TransactionError,
    ValidationError,
)
from protean.fields import Identifier, String
from protean.utils.mixins import UnitOfWork
from tests.docs.support import DOCS_SRC, REPO_ROOT, load_example

pytestmark = pytest.mark.no_test_domain


def activated(module, *, sync=True):
    if sync:
        module.domain.config["event_processing"] = "sync"
    module.domain.init(traverse=False)
    return module.domain.domain_context()


@pytest.fixture
def catalog():
    module = load_example("guides/consume-state/002.py")
    with activated(module):
        yield module


@pytest.fixture
def orders():
    module = load_example("guides/consume-state/projectors/001.py")
    with activated(module):
        yield module


@pytest.fixture
def customers():
    module = load_example("guides/consume-state/projectors/002.py")
    with activated(module):
        yield module


@pytest.fixture
def profiles():
    module = load_example("guides/consume-state/projectors/003.py")
    with activated(module, sync=False):
        yield module


@pytest.fixture
def ratings():
    module = load_example("guides/consume-state/projectors/004.py")
    with activated(module, sync=False):
        yield module


@pytest.fixture
def low_stock():
    module = load_example("guides/consume-state/projectors/005.py")
    module.domain.config["server"]["transient_retry"].update(
        base_delay_seconds=0.0, max_delay_seconds=0.0
    )
    with activated(module):
        yield module


@pytest.fixture
def ordering():
    module = load_example("guides/consume-state/projectors/006.py")
    with activated(module, sync=False):
        yield module


@pytest.fixture
def inventory():
    module = load_example("guides/consume-state/projectors/007.py")
    with activated(module, sync=False):
        yield module


@pytest.fixture
def active_orders():
    module = load_example("guides/consume-state/projectors/008.py")
    with activated(module):
        yield module


def persist(module, aggregate, *events):
    """Raise ``events`` on ``aggregate`` and store it, which publishes them."""
    for event in events:
        aggregate.raise_(event)
    module.domain.repository_for(type(aggregate)).add(aggregate)


def stored_messages(module, aggregate):
    stream = f"{aggregate.meta_.stream_category}-{aggregate.id}"
    return module.domain.event_store.store.read(stream)


def record(module, projection_cls, identifier):
    return module.domain.repository_for(projection_cls).get(identifier)


class TestDefiningAProjector:
    def test_product_added_creates_the_inventory_record(self, catalog):
        product = catalog.Product.create(
            name="Laptop",
            description="High-performance laptop",
            price=999.99,
            stock_quantity=50,
        )
        catalog.domain.repository_for(catalog.Product).add(product)

        inventory = record(catalog, catalog.ProductInventory, product.id)
        assert inventory.name == "Laptop"
        assert inventory.description == "High-performance laptop"
        assert inventory.price == 999.99
        assert inventory.stock_quantity == 50
        assert inventory.last_updated is not None

    def test_stock_adjusted_updates_inventory_and_catalog(self, catalog):
        product = catalog.Product.create(
            name="Laptop",
            description="High-performance laptop",
            price=999.99,
            stock_quantity=50,
        )
        repo = catalog.domain.repository_for(catalog.Product)
        repo.add(product)
        product.adjust_stock(-30)
        repo.add(product)
        assert (
            record(catalog, catalog.ProductInventory, product.id).stock_quantity == 20
        )
        assert record(catalog, catalog.ProductCatalog, product.id).in_stock == "YES"

        product.adjust_stock(-20)
        repo.add(product)

        assert record(catalog, catalog.ProductInventory, product.id).stock_quantity == 0
        assert record(catalog, catalog.ProductCatalog, product.id).in_stock == "NO"

    def test_a_projector_without_projector_for_raises(self):
        domain = Domain(name="Bare")

        @domain.aggregate
        class Thing:
            name: String()

        @domain.event(part_of=Thing)
        class ThingMade:
            thing_id: Identifier()

        @domain.projection
        class ThingView:
            thing_id: Identifier(identifier=True)

        with pytest.raises(
            IncorrectUsageError, match="needs to be associated with a Projection"
        ):

            @domain.projector(aggregates=[Thing])
            class ThingProjector:
                @on(ThingMade)
                def on_thing_made(self, event):
                    pass


class TestEventHandlingWithOn:
    def test_order_summary_follows_created_then_shipped(self, orders):
        order = orders.Order(customer_name="Ada")
        persist(
            orders,
            order,
            orders.OrderCreated(order_id=order.id, customer_name="Ada"),
        )

        summary = record(orders, orders.OrderSummary, order.id)
        assert summary.customer_name == "Ada"
        assert summary.status == "CREATED"

        persist(orders, order, orders.OrderShipped(order_id=order.id, carrier="DHL"))

        assert record(orders, orders.OrderSummary, order.id).status == "SHIPPED"

    def test_two_projectors_handle_the_same_shipped_event(self, orders):
        order = orders.Order(customer_name="Ada")
        persist(
            orders,
            order,
            orders.OrderCreated(order_id=order.id, customer_name="Ada"),
            orders.OrderShipped(order_id=order.id, carrier="DHL"),
        )

        assert record(orders, orders.OrderSummary, order.id).status == "SHIPPED"
        assert record(orders, orders.ShippingReport, order.id).carrier == "DHL"

    def test_cancelled_order_is_marked_cancelled(self, orders):
        order = orders.Order(customer_name="Ada")
        persist(
            orders,
            order,
            orders.OrderCreated(order_id=order.id, customer_name="Ada"),
            orders.OrderCancelled(order_id=order.id),
        )

        assert record(orders, orders.OrderSummary, order.id).status == "CANCELLED"
        with pytest.raises(ObjectNotFoundError):
            record(orders, orders.ShippingReport, order.id)


class TestCrossAggregateProjections:
    def test_summary_combines_customer_order_and_payment_events(self, customers):
        ex = customers
        customer = ex.Customer(name="Ada")
        persist(
            ex,
            customer,
            ex.CustomerRegistered(customer_id=customer.id, name="Ada"),
        )
        for total in (30.0, 12.5):
            order = ex.Order(customer_id=customer.id, total=total)
            persist(
                ex,
                order,
                ex.OrderPlaced(order_id=order.id, customer_id=customer.id, total=total),
            )
        payment = ex.Payment(customer_id=customer.id, amount=30.0)
        persist(
            ex,
            payment,
            ex.PaymentProcessed(
                payment_id=payment.id, customer_id=customer.id, amount=30.0
            ),
        )

        summary = record(ex, ex.CustomerOrderSummary, customer.id)
        assert summary.name == "Ada"
        assert summary.order_count == 2
        assert summary.order_total == 42.5
        assert summary.amount_paid == 30.0

    def test_stream_categories_are_qualified_with_the_domain_name(self, customers):
        assert customers.Customer.meta_.stream_category == "shop::customer"
        assert customers.Inventory.meta_.stream_category == "shop::inventory"

    def test_system_metrics_counts_events_from_the_listed_streams(self, customers):
        ex = customers
        customer = ex.Customer(name="Ada")
        persist(
            ex,
            customer,
            ex.CustomerRegistered(customer_id=customer.id, name="Ada"),
        )
        order = ex.Order(customer_id=customer.id, total=10.0)
        persist(
            ex,
            order,
            ex.OrderPlaced(order_id=order.id, customer_id=customer.id, total=10.0),
        )

        metrics = record(ex, ex.SystemMetrics, "all")
        assert metrics.customers == 1
        assert metrics.orders == 1


class TestIdempotency:
    def test_a_redelivered_registration_keeps_the_first_profile(self, profiles):
        ex = profiles
        user = ex.User(email="ada@example.com", name="Ada")
        persist(
            ex,
            user,
            ex.UserRegistered(user_id=user.id, email="ada@example.com", name="Ada"),
        )
        [message] = stored_messages(ex, user)

        ex.UserProfileProjector._handle(message)
        ex.UserProfileProjector._handle(message)

        profiles_stored = ex.domain.repository_for(ex.UserProfile).query.all().items
        assert [(p.user_id, p.email, p.name) for p in profiles_stored] == [
            (user.id, "ada@example.com", "Ada")
        ]

    def test_an_existing_profile_is_not_overwritten(self, profiles):
        ex = profiles
        user = ex.User(email="ada@example.com", name="Ada")
        persist(
            ex,
            user,
            ex.UserRegistered(user_id=user.id, email="ada@example.com", name="Ada"),
            ex.UserRegistered(user_id=user.id, email="other@example.com", name="X"),
        )
        first, second = stored_messages(ex, user)

        ex.UserProfileProjector._handle(first)
        ex.UserProfileProjector._handle(second)

        profile = record(ex, ex.UserProfile, user.id)
        assert profile.email == "ada@example.com"
        assert profile.name == "Ada"

    def test_idempotent_true_applies_a_redelivered_review_once(self, ratings):
        ex = ratings
        product = ex.Product(name="Desk")
        ex.domain.repository_for(ex.ProductStats).add(
            ex.ProductStats(product_id=product.id)
        )
        persist(ex, product, ex.ReviewApproved(review_id="r-1", product_id=product.id))
        [message] = stored_messages(ex, product)

        ex.RatingProjector._handle(message)
        ex.RatingProjector._handle(message)

        assert record(ex, ex.ProductStats, product.id).total_reviews == 1

    def test_distinct_reviews_are_each_counted(self, ratings):
        ex = ratings
        product = ex.Product(name="Desk")
        ex.domain.repository_for(ex.ProductStats).add(
            ex.ProductStats(product_id=product.id)
        )
        persist(
            ex,
            product,
            ex.ReviewApproved(review_id="r-1", product_id=product.id),
            ex.ReviewApproved(review_id="r-2", product_id=product.id),
        )

        for message in stored_messages(ex, product):
            ex.RatingProjector._handle(message)

        assert record(ex, ex.ProductStats, product.id).total_reviews == 2


@pytest.fixture
def failing_attempts(monkeypatch):
    """Make the first handler attempts fail with the given exceptions.

    The failure is raised where each attempt opens its Unit of Work. Returns
    the list of attempts made.
    """
    attempts = []
    failures = []

    class UnitOfWorkThatFails(UnitOfWork):
        def __enter__(self):
            attempts.append(len(attempts) + 1)
            if failures:
                raise failures.pop(0)
            return super().__enter__()

    monkeypatch.setattr("protean.utils.mixins.UnitOfWork", UnitOfWorkThatFails)

    def fail_with(*exceptions):
        failures.extend(exceptions)
        return attempts

    return fail_with


class TestTransientFailureRetries:
    def test_transaction_error_is_retried_and_the_report_is_written(
        self, low_stock, failing_attempts
    ):
        ex = low_stock
        item = ex.InventoryItem(sku="SKU-1", quantity=0)
        attempts = failing_attempts(TransactionError("conflict"), TransactionError("x"))

        persist(ex, item, ex.StockDepleted(item_id=item.id, sku="SKU-1"))

        assert attempts == [1, 2, 3]
        report = record(ex, ex.LowStockReport, item.id)
        assert report.sku == "SKU-1"
        assert report.status == "OUT_OF_STOCK"

    def test_an_exception_outside_retry_exceptions_is_not_retried(
        self, low_stock, failing_attempts
    ):
        ex = low_stock
        item = ex.InventoryItem(sku="SKU-1", quantity=0)
        attempts = failing_attempts(ValueError("not transient"))

        with pytest.raises(TransactionError, match="ValueError: not transient"):
            persist(ex, item, ex.StockDepleted(item_id=item.id, sku="SKU-1"))

        assert attempts == [1]
        with pytest.raises(ObjectNotFoundError):
            record(ex, ex.LowStockReport, item.id)

    def test_a_rerun_takes_the_update_path(self, low_stock):
        ex = low_stock
        item = ex.InventoryItem(sku="SKU-1", quantity=0)
        persist(ex, item, ex.StockDepleted(item_id=item.id, sku="SKU-1"))
        persist(ex, item, ex.StockDepleted(item_id=item.id, sku="SKU-1"))

        reports = ex.domain.repository_for(ex.LowStockReport).query.all().items
        assert [(r.item_id, r.status) for r in reports] == [(item.id, "OUT_OF_STOCK")]


class TestEventOrdering:
    def test_a_newer_shipped_event_updates_the_status(self, ordering):
        ex = ordering
        order = ex.Order(customer_name="Ada")
        persist(ex, order, ex.OrderCreated(order_id=order.id))
        persist(ex, order, ex.OrderShipped(order_id=order.id))
        created, shipped = stored_messages(ex, order)

        ex.OrderStatusProjector._handle(created)
        ex.OrderStatusProjector._handle(shipped)

        status = record(ex, ex.OrderStatus, order.id)
        assert status.status == "SHIPPED"
        assert status.last_updated == shipped.metadata.headers.time

    def test_an_older_shipped_event_is_ignored(self, ordering):
        ex = ordering
        order = ex.Order(customer_name="Ada")
        persist(ex, order, ex.OrderShipped(order_id=order.id))
        persist(ex, order, ex.OrderCreated(order_id=order.id))
        shipped, created = stored_messages(ex, order)

        ex.OrderStatusProjector._handle(created)
        ex.OrderStatusProjector._handle(shipped)

        status = record(ex, ex.OrderStatus, order.id)
        assert status.status == "CREATED"
        assert status.last_updated == created.metadata.headers.time


class TestErrorHandling:
    def test_product_added_creates_inventory_once(self, inventory):
        ex = inventory
        product = ex.Product(name="Mouse", price=25.0)
        persist(
            ex,
            product,
            ex.ProductAdded(
                product_id=product.id, name="Mouse", price=25.0, stock_quantity=12
            ),
            ex.ProductAdded(
                product_id=product.id, name="Other", price=1.0, stock_quantity=1
            ),
        )
        first, duplicate = stored_messages(ex, product)

        ex.ProductInventoryProjector._handle(first)
        ex.ProductInventoryProjector._handle(duplicate)

        item = record(ex, ex.ProductInventory, product.id)
        assert (item.name, item.price, item.stock_quantity) == ("Mouse", 25.0, 12)

    def test_a_failure_is_logged_and_raised_again(self, inventory, caplog):
        ex = inventory
        product = ex.Product(name="Mouse", price=25.0)
        long_name = "M" * 60
        persist(
            ex,
            product,
            ex.ProductAdded(
                product_id=product.id, name=long_name, price=25.0, stock_quantity=12
            ),
        )
        [message] = stored_messages(ex, product)

        with pytest.raises(ValidationError, match="name"):
            ex.ProductInventoryProjector._handle(message)

        assert "Failed to process ProductAdded event" in caplog.text
        with pytest.raises(ObjectNotFoundError):
            record(ex, ex.ProductInventory, product.id)


class TestHandlingDeletions:
    def test_delivered_order_is_removed_from_active_orders(self, active_orders):
        ex = active_orders
        order = ex.Order(customer_name="Ada")
        persist(
            ex,
            order,
            ex.OrderPlaced(order_id=order.id, customer_name="Ada"),
        )

        active = record(ex, ex.ActiveOrder, order.id)
        assert (active.customer_name, active.status) == ("Ada", "placed")

        persist(ex, order, ex.OrderDelivered(order_id=order.id))

        with pytest.raises(ObjectNotFoundError):
            record(ex, ex.ActiveOrder, order.id)

    def test_only_the_delivered_order_is_removed(self, active_orders):
        ex = active_orders
        kept = ex.Order(customer_name="Bo")
        persist(ex, kept, ex.OrderPlaced(order_id=kept.id, customer_name="Bo"))
        gone = ex.Order(customer_name="Ada")
        persist(ex, gone, ex.OrderPlaced(order_id=gone.id, customer_name="Ada"))

        persist(ex, gone, ex.OrderDelivered(order_id=gone.id))

        remaining = ex.domain.repository_for(ex.ActiveOrder).query.all().items
        assert [r.order_id for r in remaining] == [kept.id]


class TestTestingProjectors:
    def test_testing_example_loads(self):
        module = load_example("guides/consume-state/projectors/009.py")
        assert callable(module.test_product_inventory_projector_on_product_added)
        assert callable(module.test_projector_integration)

    def test_page_tests_pass_under_pytest(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(DOCS_SRC / "guides/consume-state/projectors/009.py"),
                "-p",
                "no:cacheprovider",
                "-p",
                "no:randomly",
                "-q",
                "--import-mode=importlib",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert re.search(r"\b2 passed\b", result.stdout), output
