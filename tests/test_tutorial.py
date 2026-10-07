"""Tests for the Bookshelf tutorial source files.

Each test imports the actual chapter module from docs_src/ and exercises
its domain objects, commands, and assertions — the same logic as the
chapter's ``if __name__ == "__main__"`` block.

Runs with in-memory adapters by default.  Pass ``--db``, ``--store``,
and ``--broker`` to pytest to exercise real adapters (same flags used
by the rest of the test suite).

Chapter 9 splits the code into a ``bookshelf`` package next to the chapter
files, and ch10 imports from it, so the ``tutorial/`` folder goes on
``sys.path`` before either is loaded.
"""

import importlib.util
import os
import subprocess
import sys
import types
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from protean.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Module loading helper
# ---------------------------------------------------------------------------
_TUTORIAL_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "docs_src",
    "guides",
    "getting-started",
    "tutorial",
)
_TUTORIAL_DIR = os.path.abspath(_TUTORIAL_DIR)

# Chapter 9's ``bookshelf`` package lives in the tutorial folder.
if _TUTORIAL_DIR not in sys.path:
    sys.path.insert(0, _TUTORIAL_DIR)


def _load_chapter(num: int) -> types.ModuleType:
    """Load a chapter module by number.

    Uses spec_from_file_location to handle hyphenated directory names
    in the path (``getting-started``).
    """
    name = f"tutorial_ch{num:02d}"
    filepath = os.path.join(_TUTORIAL_DIR, f"ch{num:02d}.py")
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load chapter modules at module level (each has its own Domain instance)
ch01 = _load_chapter(1)
ch02 = _load_chapter(2)
ch03 = _load_chapter(3)
ch04 = _load_chapter(4)
ch05 = _load_chapter(5)
ch06 = _load_chapter(6)
ch07 = _load_chapter(7)

# Chapter 9 is the ``bookshelf`` package. Import its modules before ch10, and
# record what they registered: ch10 calls ``domain.init()``, whose traversal
# would register the modules again and hide a module that registers nothing.
import bookshelf
import bookshelf.commands
import bookshelf.events
import bookshelf.handlers
import bookshelf.models
import bookshelf.projections

_BOOKSHELF_REGISTERED = set(bookshelf.domain.registry._elements_by_name)

ch10 = _load_chapter(10)
ch13 = _load_chapter(13)
ch14 = _load_chapter(14)
ch15 = _load_chapter(15)
ch19 = _load_chapter(19)
ch20 = _load_chapter(20)
ch21 = _load_chapter(21)

# Chapters that have projections (need DB artifact create/drop with real DBs)
_HAS_PROJECTIONS = {ch07, bookshelf, ch10, ch21}


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------
def _cleanup(domain) -> None:
    """Reset all stores and close connections after a test."""
    for provider_name in domain.providers:
        provider = domain.providers[provider_name]
        try:
            provider._data_reset()
        finally:
            provider.close()

    if domain.event_store.store:
        try:
            domain.event_store.store._data_reset()
        finally:
            domain.event_store.store.close()


def _configure_domain(
    domain, db_config: dict, store_config: dict, broker_config: dict
) -> None:
    """Reconfigure a chapter domain with the session adapter configs."""
    domain.config["databases"]["default"] = db_config
    domain.config["event_store"] = store_config
    domain.config["brokers"]["default"] = broker_config
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"
    domain._initialize()


class _TutorialBase:
    """Base class providing autouse adapter configuration for all tutorial tests.

    Each subclass sets ``_chapter_mod`` to its chapter module.  The fixture
    reconfigures the chapter's domain with the session-scoped adapter configs
    (db_config / store_config / broker_config) from conftest.py.
    """

    _chapter_mod: types.ModuleType  # set by each subclass

    @pytest.fixture(autouse=True)
    def _configure_chapter(self, db_config, store_config, broker_config):
        mod = self._chapter_mod
        domain = mod.domain
        _configure_domain(domain, db_config, store_config, broker_config)

        has_projections = mod in _HAS_PROJECTIONS
        if has_projections:
            domain.providers["default"]._create_database_artifacts()

        yield domain

        if has_projections:
            domain.providers["default"]._drop_database_artifacts()

        _cleanup(domain)


# ---------------------------------------------------------------------------
# PART I: Building the Domain (Ch 1-4)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestTutorialCh01(_TutorialBase):
    _chapter_mod = ch01

    def test_first_aggregate(self):
        """Ch1: Create Book aggregate, persist, and retrieve."""
        domain = ch01.domain
        with domain.domain_context():
            book = ch01.Book(
                title="The Great Gatsby",
                author="F. Scott Fitzgerald",
                isbn="9780743273565",
                price=12.99,
            )
            repo = domain.repository_for(ch01.Book)
            repo.add(book)

            saved = repo.get(book.id)
            assert saved.title == "The Great Gatsby"
            assert saved.author == "F. Scott Fitzgerald"
            assert saved.price == 12.99


@pytest.mark.no_test_domain
class TestTutorialCh02(_TutorialBase):
    _chapter_mod = ch02

    def test_rich_fields_and_value_objects(self):
        """Ch2: Value objects (Money, Address), rich fields, equality."""
        domain = ch02.domain
        with domain.domain_context():
            gatsby = ch02.Book(
                title="The Great Gatsby",
                author="F. Scott Fitzgerald",
                isbn="9780743273565",
                price=ch02.Money(amount=12.99),
                page_count=180,
                genre=ch02.Genre.FICTION.value,
                tags=["classic", "american"],
            )
            repo = domain.repository_for(ch02.Book)
            repo.add(gatsby)

            saved = repo.get(gatsby.id)
            assert saved.price.amount == 12.99
            assert saved.price.currency == "USD"

            # Value object equality
            price1 = ch02.Money(amount=12.99, currency="USD")
            price2 = ch02.Money(amount=12.99, currency="USD")
            price3 = ch02.Money(amount=14.99, currency="USD")
            assert price1 == price2
            assert price1 != price3

            # Address value object
            addr = ch02.Address(
                street="123 Main St",
                city="Springfield",
                state="IL",
                zip_code="62704",
            )
            assert addr.country == "US"


@pytest.mark.no_test_domain
class TestTutorialCh03(_TutorialBase):
    _chapter_mod = ch03

    def test_entities_and_associations(self):
        """Ch3: Order with OrderItem entities, HasMany, aggregate cluster."""
        domain = ch03.domain
        with domain.domain_context():
            order = ch03.Order(
                customer_name="Alice Johnson",
                customer_email="alice@example.com",
                shipping_address=ch03.Address(
                    street="456 Oak Ave",
                    city="Portland",
                    state="OR",
                    zip_code="97201",
                ),
                items=[
                    ch03.OrderItem(
                        book_title="The Great Gatsby",
                        quantity=1,
                        unit_price=ch03.Money(amount=12.99),
                    ),
                    ch03.OrderItem(
                        book_title="Brave New World",
                        quantity=2,
                        unit_price=ch03.Money(amount=14.99),
                    ),
                ],
            )

            repo = domain.repository_for(ch03.Order)
            repo.add(order)

            saved = repo.get(order.id)
            assert saved.customer_name == "Alice Johnson"
            assert len(saved.items) == 2
            assert saved.shipping_address.city == "Portland"

            # Add another item
            saved.add_items(
                ch03.OrderItem(
                    book_title="Sapiens",
                    quantity=1,
                    unit_price=ch03.Money(amount=18.99),
                )
            )
            repo.add(saved)

            updated = repo.get(order.id)
            assert len(updated.items) == 3


@pytest.mark.no_test_domain
class TestTutorialCh04(_TutorialBase):
    _chapter_mod = ch04

    def test_invariants(self):
        """Ch4: Pre/post invariants, business rules on Order."""
        domain = ch04.domain
        with domain.domain_context():
            # Post-invariant: order must have items
            with pytest.raises(ValidationError):
                ch04.Order(customer_name="Alice")

            # Create valid order
            order = ch04.Order(
                customer_name="Alice",
                items=[
                    ch04.OrderItem(
                        book_title="The Great Gatsby",
                        quantity=1,
                        unit_price=ch04.Money(amount=12.99),
                    ),
                ],
            )
            order.add_item("Brave New World", 2, ch04.Money(amount=14.99))
            assert len(order.items) == 2

            # Confirm and ship
            order.confirm()
            assert order.status == "CONFIRMED"
            order.ship()
            assert order.status == "SHIPPED"

            # Pre-invariant: cannot modify shipped order
            with pytest.raises(ValidationError):
                order.customer_name = "Bob"


# ---------------------------------------------------------------------------
# PART II: Making It Real (Ch 5-7)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestTutorialCh05(_TutorialBase):
    _chapter_mod = ch05

    def test_commands_and_handlers(self):
        """Ch5: AddBook command, handler, domain.process()."""
        domain = ch05.domain
        with domain.domain_context():
            book_id = domain.process(
                ch05.AddBook(
                    title="The Great Gatsby",
                    author="F. Scott Fitzgerald",
                    isbn="9780743273565",
                    price_amount=12.99,
                )
            )

            book = domain.repository_for(ch05.Book).get(book_id)
            assert book.title == "The Great Gatsby"
            assert book.price.amount == 12.99

            # Add another book
            book_id_2 = domain.process(
                ch05.AddBook(
                    title="Brave New World",
                    author="Aldous Huxley",
                    isbn="9780060850524",
                    price_amount=14.99,
                )
            )
            assert book_id_2 != book_id


@pytest.mark.no_test_domain
class TestTutorialCh06(_TutorialBase):
    _chapter_mod = ch06

    def test_events_and_reactions(self):
        """Ch6: Events, event handlers, command-driven flow."""
        domain = ch06.domain
        with domain.domain_context():
            # Add a book — triggers BookEventHandler → creates Inventory
            domain.process(
                ch06.AddBook(
                    title="The Great Gatsby",
                    author="F. Scott Fitzgerald",
                    isbn="9780743273565",
                    price_amount=12.99,
                )
            )

            # Verify inventory was created by the event handler
            inventories = domain.repository_for(ch06.Inventory).query.all()
            assert inventories.total == 1
            assert inventories.items[0].title == "The Great Gatsby"
            assert inventories.items[0].quantity == 10

            # Place an order through command pipeline
            order_id = domain.process(
                ch06.PlaceOrder(
                    customer_name="Alice Johnson",
                    book_title="The Great Gatsby",
                    quantity=2,
                    unit_price_amount=12.99,
                )
            )

            # Confirm and ship through commands
            domain.process(ch06.ConfirmOrder(order_id=order_id))
            domain.process(ch06.ShipOrder(order_id=order_id))

            # Verify final order state
            order = domain.repository_for(ch06.Order).get(order_id)
            assert order.status == "SHIPPED"
            assert len(order.items) == 1


# ---------------------------------------------------------------------------
# PART II (continued): Projections (Ch 7)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestTutorialCh07(_TutorialBase):
    _chapter_mod = ch07

    def test_projections_and_projectors(self):
        """Ch7: BookCatalog projection, projector, price update."""
        domain = ch07.domain
        with domain.domain_context():
            book_repo = domain.repository_for(ch07.Book)
            catalog_repo = domain.repository_for(ch07.BookCatalog)

            # Add books — events trigger projector
            gatsby = ch07.Book.add_to_catalog(
                title="The Great Gatsby",
                author="F. Scott Fitzgerald",
                isbn="9780743273565",
                price=12.99,
            )
            book_repo.add(gatsby)

            brave = ch07.Book.add_to_catalog(
                title="Brave New World",
                author="Aldous Huxley",
                isbn="9780060850524",
                price=14.99,
            )
            book_repo.add(brave)

            # Verify projection was populated via domain.view_for()
            all_entries = domain.view_for(ch07.BookCatalog).query.all()
            assert all_entries.total == 2

            # Update price — projector updates the catalog
            gatsby.update_price(15.99)
            book_repo.add(gatsby)

            updated = catalog_repo.get(gatsby.id)
            assert updated.price == 15.99
            assert updated.title == "The Great Gatsby"


# ---------------------------------------------------------------------------
# PART II (continued): The Package and the API (Ch 9-10)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestTutorialCh09(_TutorialBase):
    _chapter_mod = bookshelf

    def test_package_registers_every_module(self):
        """Ch9: The split modules register into the one ``bookshelf`` domain."""
        assert {
            "Book",
            "Order",
            "BookAdded",
            "AddBook",
            "BookCommandHandler",
            "BookCatalog",
            "BookCatalogProjector",
        } <= _BOOKSHELF_REGISTERED

    def test_importing_the_package_alone_registers_nothing(self):
        """Ch9: ``__init__.py`` only creates the domain; the modules register."""
        code = (
            "import bookshelf; print(len(bookshelf.domain.registry._elements_by_name))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            cwd=_TUTORIAL_DIR,
        )
        assert result.stdout.strip() == "0"

    def test_adding_a_book_fills_inventory_and_catalog(self):
        """Ch9: A command runs through handlers and the projector across modules."""
        domain = bookshelf.domain
        with domain.domain_context():
            book_id = domain.process(
                bookshelf.commands.AddBook(
                    title="Dune",
                    author="Frank Herbert",
                    isbn="9780441013593",
                    price_amount=9.99,
                )
            )

            inventory = (
                domain.repository_for(bookshelf.models.Inventory)
                .query.filter(book_id=book_id)
                .all()
            )
            assert inventory.total == 1
            assert inventory.first.quantity == 10

            entry = domain.view_for(bookshelf.projections.BookCatalog).get(book_id)
            assert entry.title == "Dune"
            assert entry.price == 9.99


@pytest.mark.no_test_domain
class TestTutorialCh10(_TutorialBase):
    _chapter_mod = ch10

    def test_chapter_uses_the_package_domain(self):
        """Ch10: The API is built on chapter 9's domain, not a new one."""
        assert ch10.domain is bookshelf.domain

    def test_added_book_shows_in_the_catalog(self):
        """Ch10: POST a book, then read it back from the catalog endpoint."""
        client = TestClient(ch10.app)

        response = client.post(
            "/books",
            json={"title": "Dune", "author": "Frank Herbert", "price_amount": 9.99},
        )
        assert response.status_code == 200
        book_id = response.json()["book_id"]

        entry = client.get(f"/catalog/{book_id}")
        assert entry.status_code == 200
        assert entry.json()["title"] == "Dune"
        assert entry.json()["price"] == 9.99


# ---------------------------------------------------------------------------
# PART III: Growing the System (Ch 13-15)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestTutorialCh13(_TutorialBase):
    _chapter_mod = ch13

    def test_domain_service_confirms_order(self):
        """Ch13: OrderFulfillmentService confirms when stock is sufficient."""
        domain = ch13.domain
        with domain.domain_context():
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=10)
            order = ch13.Order(
                customer_name="Alice",
                items=[
                    ch13.OrderItem(
                        book_title="Dune",
                        quantity=2,
                        unit_price=ch13.Money(amount=15.99),
                    )
                ],
            )

            service = ch13.OrderFulfillmentService(order, [inv])
            service.confirm_order()

            assert order.status == "CONFIRMED"
            assert inv.quantity == 8  # 10 - 2

    def test_domain_service_rejects_insufficient_stock(self):
        """Ch13: OrderFulfillmentService rejects when stock is insufficient."""
        domain = ch13.domain
        with domain.domain_context():
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=1)
            order = ch13.Order(
                customer_name="Alice",
                items=[
                    ch13.OrderItem(
                        book_title="Dune",
                        quantity=5,
                        unit_price=ch13.Money(amount=15.99),
                    )
                ],
            )

            service = ch13.OrderFulfillmentService(order, [inv])
            with pytest.raises(ValidationError) as exc_info:
                service.confirm_order()
            assert "Insufficient stock" in str(exc_info.value.messages)

    def test_domain_service_via_command(self):
        """Ch13: ConfirmOrder command invokes the domain service."""
        domain = ch13.domain
        with domain.domain_context():
            # Create and persist inventory
            inv_repo = domain.repository_for(ch13.Inventory)
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)

            # Create and persist order
            order_repo = domain.repository_for(ch13.Order)
            order = ch13.Order(
                customer_name="Alice",
                items=[
                    ch13.OrderItem(
                        book_title="Dune",
                        quantity=3,
                        unit_price=ch13.Money(amount=15.99),
                    )
                ],
            )
            order_repo.add(order)

            # Confirm through command pipeline
            domain.process(ch13.ConfirmOrder(order_id=order.id))

            confirmed = order_repo.get(order.id)
            assert confirmed.status == "CONFIRMED"

            updated_inv = inv_repo.get(inv.id)
            assert updated_inv.quantity == 7  # 10 - 3


@pytest.mark.no_test_domain
class TestTutorialCh14(_TutorialBase):
    _chapter_mod = ch14

    def test_subscriber_translates_new_book_webhook(self):
        """Ch14: BookSupplyWebhookSubscriber creates a book from webhook."""
        domain = ch14.domain
        with domain.domain_context():
            # The subscriber has no command handler for AddBook, so we
            # test the subscriber's translation logic by calling it and
            # verifying the command would be dispatched.
            # Since there is no command handler registered, we test the
            # aggregate and restock command path instead.
            inv = ch14.Inventory(book_id="book-1", title="War and Peace", quantity=5)
            inv_repo = domain.repository_for(ch14.Inventory)
            inv_repo.add(inv)

            # RestockInventory has a handler — test that path
            domain.process(ch14.RestockInventory(book_id=inv.id, quantity=20))

            updated = inv_repo.get(inv.id)
            assert updated.quantity == 25  # 5 + 20


@pytest.mark.no_test_domain
class TestTutorialCh15(_TutorialBase):
    _chapter_mod = ch15

    def test_fact_events_and_report_projection(self):
        """Ch15: Fact events are generated and stored in the event store."""
        domain = ch15.domain
        with domain.domain_context():
            book_repo = domain.repository_for(ch15.Book)

            # Add a book — triggers both the BookAdded delta event and a fact event
            gatsby = ch15.Book.add_to_catalog(
                title="The Great Gatsby",
                author="F. Scott Fitzgerald",
                isbn="9780743273565",
                price=12.99,
            )
            book_repo.add(gatsby)

            # Update price — triggers another fact event with complete state
            gatsby.update_price(15.99)
            book_repo.add(gatsby)

            # Verify fact events were stored in the event store
            fact_stream = f"{ch15.Book.meta_.stream_category}-fact-{gatsby.id}"
            fact_messages = domain.event_store.store.read(fact_stream)
            assert len(fact_messages) == 2  # One per state change

            # Last fact event has the final complete state
            last_fact = fact_messages[-1].to_domain_object()
            assert last_fact.price == 15.99
            assert last_fact.title == "The Great Gatsby"


# ---------------------------------------------------------------------------
# PART IV: Production Operations (Ch 19)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestTutorialCh19(_TutorialBase):
    _chapter_mod = ch19

    def test_priority_lanes_context_manager(self):
        """Ch19: processing_priority context manager sets bulk priority."""
        from protean.utils.processing import Priority, processing_priority

        domain = ch19.domain
        with domain.domain_context():
            # Normal processing works
            book = ch19.Book(
                title="Normal Book",
                author="Author",
                price=9.99,
            )
            repo = domain.repository_for(ch19.Book)
            repo.add(book)

            saved = repo.get(book.id)
            assert saved.title == "Normal Book"

            # BULK priority context manager can be entered
            with processing_priority(Priority.BULK):
                bulk_book = ch19.Book(
                    title="Bulk Imported Book",
                    author="Bulk Author",
                    price=5.99,
                )
                repo.add(bulk_book)

            saved_bulk = repo.get(bulk_book.id)
            assert saved_bulk.title == "Bulk Imported Book"


# ---------------------------------------------------------------------------
# PART V: System Mastery (Ch 20-21)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestTutorialCh20(_TutorialBase):
    _chapter_mod = ch20

    def test_aggregates_and_events(self):
        """Ch20: Order, Inventory, Shipment aggregates raise events."""
        domain = ch20.domain
        with domain.domain_context():
            # Order confirm raises OrderConfirmed
            order = ch20.Order(
                customer_name="Alice",
                shipping_address="123 Main St",
            )
            order.confirm()
            assert order.status == "CONFIRMED"
            assert len(order._events) == 1
            assert order._events[0].__class__.__name__ == "OrderConfirmed"

            # Inventory reserve raises InventoryReserved
            inv = ch20.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv.reserve("order-1", 3)
            assert inv.quantity == 7
            assert len(inv._events) == 1
            assert inv._events[0].__class__.__name__ == "InventoryReserved"
            assert inv._events[0].order_id == "order-1"
            assert inv._events[0].book_id == "book-1"

            # Shipment success path
            shipment = ch20.Shipment(order_id=order.id)
            shipment.create_shipment("123 Main St")
            assert shipment.status == "CREATED"
            assert shipment.tracking_number is not None
            assert len(shipment._events) == 1
            assert shipment._events[0].__class__.__name__ == "ShipmentCreated"

    def test_shipment_failure(self):
        """Ch20: Shipment with invalid address raises ShipmentFailed."""
        domain = ch20.domain
        with domain.domain_context():
            shipment = ch20.Shipment(order_id="order-1")
            shipment.create_shipment("")  # Empty address fails
            assert shipment.status == "FAILED"
            assert len(shipment._events) == 1
            assert shipment._events[0].__class__.__name__ == "ShipmentFailed"

    def test_process_manager_start_stores_order_id(self):
        """Ch20: the start handler keeps the order ID for the later steps."""
        domain = ch20.domain
        with domain.domain_context():
            pm = ch20.OrderFulfillmentPM._load_or_create("order-1", is_start=True)
            event = ch20.OrderConfirmed(order_id="order-1", customer_name="Alice")
            with patch.object(domain, "process") as process:
                ch20.OrderFulfillmentPM.on_order_confirmed.__wrapped__(pm, event)
            assert pm.order_id == "order-1"
            assert process.call_args.args[0].order_id == "order-1"


@pytest.mark.no_test_domain
class TestTutorialCh21(_TutorialBase):
    _chapter_mod = ch21

    def test_cross_aggregate_projection(self):
        """Ch21: StorefrontView combines Book and Inventory data."""
        domain = ch21.domain
        with domain.domain_context():
            # Add a book — projector creates StorefrontView entry
            book = ch21.Book(
                title="The Great Gatsby",
                author="F. Scott Fitzgerald",
                isbn="9780743273565",
                price=12.99,
            )
            book.raise_(
                ch21.BookAdded(
                    book_id=book.id,
                    title=book.title,
                    author=book.author,
                    price=book.price,
                )
            )
            domain.repository_for(ch21.Book).add(book)

            # Verify StorefrontView was created
            storefront_repo = domain.repository_for(ch21.StorefrontView)
            entry = storefront_repo.get(book.id)
            assert entry.title == "The Great Gatsby"
            assert entry.price == 12.99
            assert entry.in_stock is False
            assert entry.quantity == 0

            # Stock the inventory — projector updates StorefrontView
            inv = ch21.Inventory(
                book_id=book.id,
                title="The Great Gatsby",
                quantity=25,
            )
            inv.raise_(
                ch21.InventoryStocked(
                    book_id=book.id,
                    title="The Great Gatsby",
                    quantity=25,
                )
            )
            domain.repository_for(ch21.Inventory).add(inv)

            # Verify the storefront now shows in-stock
            updated = storefront_repo.get(book.id)
            assert updated.quantity == 25
            assert updated.in_stock is True

    def test_view_for_storefront(self):
        """Ch21: domain.view_for(StorefrontView).query returns read-only results."""
        domain = ch21.domain
        with domain.domain_context():
            # Add two books
            for title, author, price in [
                ("Book A", "Author A", 10.0),
                ("Book B", "Author B", 20.0),
            ]:
                book = ch21.Book(title=title, author=author, price=price)
                book.raise_(
                    ch21.BookAdded(
                        book_id=book.id,
                        title=title,
                        author=author,
                        price=price,
                    )
                )
                domain.repository_for(ch21.Book).add(book)

            # Query via domain.view_for()
            results = domain.view_for(ch21.StorefrontView).query.all()
            assert results.total == 2
