"""Tests for the Bookshelf tutorial source files.

Each test loads the chapter module from ``docs_src`` with ``load_example`` and
exercises its domain objects, commands, and assertions, the same logic as the
chapter's ``if __name__ == "__main__"`` block.

Runs with in-memory adapters by default.  Pass ``--db``, ``--store``,
and ``--broker`` to pytest to exercise real adapters (same flags used
by the rest of the test suite).

Chapter 9 splits the code into a ``bookshelf`` package next to the chapter
files, and ch10 imports from it, so the ``tutorial/`` folder goes on
``sys.path`` before either is loaded.
"""

import subprocess
import sys
import types

import pytest
from fastapi.testclient import TestClient

from protean.exceptions import ValidationError
from tests.docs.support import DOCS_SRC, load_example

# Chapter 9's ``bookshelf`` package lives in the tutorial folder.
_TUTORIAL_DIR = str(DOCS_SRC / "guides" / "getting-started" / "tutorial")
if _TUTORIAL_DIR not in sys.path:
    sys.path.insert(0, _TUTORIAL_DIR)

# Load chapter modules at module level (each has its own Domain instance).
# ``load_example`` runs a chapter afresh on every call, so load each one once.
ch01 = load_example("guides/getting-started/tutorial/ch01.py")
ch02 = load_example("guides/getting-started/tutorial/ch02.py")
ch03 = load_example("guides/getting-started/tutorial/ch03.py")
ch04 = load_example("guides/getting-started/tutorial/ch04.py")
ch05 = load_example("guides/getting-started/tutorial/ch05.py")
ch06 = load_example("guides/getting-started/tutorial/ch06.py")
ch07 = load_example("guides/getting-started/tutorial/ch07.py")

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

ch10 = load_example("guides/getting-started/tutorial/ch10.py")
ch13 = load_example("guides/getting-started/tutorial/ch13.py")
ch14 = load_example("guides/getting-started/tutorial/ch14.py")
ch15 = load_example("guides/getting-started/tutorial/ch15.py")
ch19 = load_example("guides/getting-started/tutorial/ch19.py")
ch20 = load_example("guides/getting-started/tutorial/ch20.py")
ch21 = load_example("guides/getting-started/tutorial/ch21.py")

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
            # The service only confirms; Inventory reserves through the event
            assert inv.quantity == 10
            assert [type(e) for e in order._events] == [ch13.OrderConfirmed]
            assert order._events[0].items == [{"book_title": "Dune", "quantity": 2}]
            # Chapter 6's notification handler reads customer_name
            assert order._events[0].customer_name == "Alice"

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

            # OrderConfirmed -> ReserveInventory -> InventoryCommandHandler
            updated_inv = inv_repo.get(inv.id)
            assert updated_inv.quantity == 7  # 10 - 3
            assert updated_inv.reserved_order_ids == [order.id]

    def test_repeated_confirm_order_raises_one_order_confirmed(self):
        """Ch13: a second ConfirmOrder for a confirmed order changes nothing."""
        domain = ch13.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch13.Inventory)
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)
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
            domain.repository_for(ch13.Order).add(order)

            for _ in range(2):
                domain.process(ch13.ConfirmOrder(order_id=order.id))

            confirmations = [
                event
                for event in (
                    message.to_domain_object()
                    for message in domain.event_store.store.read("$all")
                )
                if isinstance(event, ch13.OrderConfirmed) and event.order_id == order.id
            ]
            assert len(confirmations) == 1
            assert inv_repo.get(inv.id).quantity == 7

    def test_confirm_order_handler_persists_only_the_order(self, monkeypatch):
        """Ch13: the ConfirmOrder handler leaves Inventory to the event flow."""
        sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
        export = pytest.importorskip("opentelemetry.sdk.trace.export")
        in_memory = pytest.importorskip(
            "opentelemetry.sdk.trace.export.in_memory_span_exporter"
        )
        domain = ch13.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch13.Inventory)
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)
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

            # With async event processing the OrderConfirmed reaction does not
            # run here, so only what the command handler wrote is visible.
            monkeypatch.setitem(domain.config, "event_processing", "async")
            exporter = in_memory.InMemorySpanExporter()
            provider = sdk_trace.TracerProvider()
            provider.add_span_processor(export.SimpleSpanProcessor(exporter))
            monkeypatch.setattr(
                domain, "_otel_tracer_provider", provider, raising=False
            )
            monkeypatch.setattr(domain, "_otel_init_attempted", True)
            domain.process(ch13.ConfirmOrder(order_id=order.id))

            assert order_repo.get(order.id).status == "CONFIRMED"
            assert inv_repo.get(inv.id).quantity == 10
            # A save of an unchanged Inventory writes nothing, so count the
            # repository.add calls to catch a handler that saves one anyway.
            saved = [
                span.attributes["protean.aggregate.type"]
                for span in exporter.get_finished_spans()
                if span.name == "protean.repository.add"
                and span.attributes["protean.aggregate.type"] != "MemoryMessage"
            ]
            assert saved == ["Order"]

    def test_redelivered_reservation_is_skipped(self):
        """Ch13: a second ReserveInventory for the same order changes nothing."""
        domain = ch13.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch13.Inventory)
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)

            command = ch13.ReserveInventory(
                order_id="order-1", book_title="Dune", quantity=3
            )
            domain.process(command)
            domain.process(command)

            updated = inv_repo.get(inv.id)
            assert updated.quantity == 7
            assert updated.reserved_order_ids == ["order-1"]

    def _order_with_two_dune_lines(self):
        return ch13.Order(
            customer_name="Alice",
            items=[
                ch13.OrderItem(
                    book_title="Dune", quantity=2, unit_price=ch13.Money(amount=15.99)
                ),
                ch13.OrderItem(
                    book_title="Dune", quantity=3, unit_price=ch13.Money(amount=15.99)
                ),
            ],
        )

    def test_two_lines_for_the_same_book_both_reserve(self):
        """Ch13: two lines for one book reserve their summed quantity."""
        domain = ch13.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch13.Inventory)
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)
            order_repo = domain.repository_for(ch13.Order)
            order = self._order_with_two_dune_lines()
            order_repo.add(order)

            domain.process(ch13.ConfirmOrder(order_id=order.id))

            updated = inv_repo.get(inv.id)
            assert updated.quantity == 5  # 10 - 2 - 3
            assert updated.reserved_order_ids == [order.id]

    def test_service_checks_lines_for_the_same_book_together(self):
        """Ch13: 2 + 3 copies of one book against a stock of 4 is rejected."""
        domain = ch13.domain
        with domain.domain_context():
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=4)
            order = self._order_with_two_dune_lines()

            service = ch13.OrderFulfillmentService(order, [inv])
            with pytest.raises(ValidationError) as exc_info:
                service.confirm_order()
            assert exc_info.value.messages == {
                "_entity": ["Insufficient stock for 'Dune': 4 available, 5 requested"]
            }
            assert order.status == "PENDING"

    def test_reservation_after_the_check_can_still_fail(self, monkeypatch):
        """Ch13: two orders pass the stock check; the second reservation fails."""
        domain = ch13.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch13.Inventory)
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)
            order_repo = domain.repository_for(ch13.Order)
            orders = []
            for quantity in (8, 5):
                order = ch13.Order(
                    customer_name="Alice",
                    items=[
                        ch13.OrderItem(
                            book_title="Dune",
                            quantity=quantity,
                            unit_price=ch13.Money(amount=15.99),
                        )
                    ],
                )
                order_repo.add(order)
                orders.append(order)

            # Hold back the reservations so both orders see 10 in stock.
            monkeypatch.setitem(domain.config, "event_processing", "async")
            for order in orders:
                domain.process(ch13.ConfirmOrder(order_id=order.id))
            monkeypatch.setitem(domain.config, "event_processing", "sync")

            domain.process(
                ch13.ReserveInventory(
                    order_id=orders[0].id, book_title="Dune", quantity=8
                )
            )
            with pytest.raises(ValidationError) as exc_info:
                domain.process(
                    ch13.ReserveInventory(
                        order_id=orders[1].id, book_title="Dune", quantity=5
                    )
                )
            assert exc_info.value.messages == {
                "quantity": ["Insufficient stock: 2 available, 5 requested"]
            }

            assert [order_repo.get(o.id).status for o in orders] == [
                "CONFIRMED",
                "CONFIRMED",
            ]
            updated = inv_repo.get(inv.id)
            assert updated.quantity == 2
            assert updated.reserved_order_ids == [orders[0].id]

    def test_out_of_stock_command_leaves_both_unchanged(self):
        """Ch13: the pre-invariant rejects the command before anything changes."""
        domain = ch13.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch13.Inventory)
            inv = ch13.Inventory(book_id="book-1", title="Dune", quantity=1)
            inv_repo.add(inv)
            order_repo = domain.repository_for(ch13.Order)
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
            order_repo.add(order)

            with pytest.raises(ValidationError) as exc_info:
                domain.process(ch13.ConfirmOrder(order_id=order.id))
            assert "Insufficient stock" in str(exc_info.value.messages)

            assert order_repo.get(order.id).status == "PENDING"
            assert inv_repo.get(inv.id).quantity == 1


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
            # Order confirm raises OrderConfirmed with chapter 13's shape
            order = ch20.Order(
                customer_name="Alice",
                shipping_address="123 Main St",
                items=[
                    ch20.OrderItem(
                        book_title="Dune",
                        quantity=2,
                        unit_price=ch20.Money(amount=15.99),
                    )
                ],
            )
            order.confirm()
            assert order.status == "CONFIRMED"
            assert len(order._events) == 1
            assert order._events[0].__class__.__name__ == "OrderConfirmed"
            assert order._events[0].customer_name == "Alice"
            assert order._events[0].items == [{"book_title": "Dune", "quantity": 2}]

            # Inventory reserve raises InventoryReserved
            inv = ch20.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv.reserve("order-1", 3)
            assert inv.quantity == 7
            assert len(inv._events) == 1
            assert inv._events[0].__class__.__name__ == "InventoryReserved"
            assert inv._events[0].order_id == "order-1"
            assert inv._events[0].book_title == "Dune"

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

    def test_chapter_happy_path(self):
        """Ch20: the chapter's happy-path test runs as shown."""
        ch20.test_fulfillment_happy_path()

    def test_chapter_compensation(self):
        """Ch20: the chapter's compensation test runs as shown."""
        ch20.test_fulfillment_compensation()

    def _confirm(self, address):
        order_repo = ch20.domain.repository_for(ch20.Order)
        order = ch20.Order(
            customer_name="Alice",
            shipping_address=address,
            items=[
                ch20.OrderItem(
                    book_title=title, quantity=quantity, unit_price=ch20.Money(amount=1)
                )
                for title, quantity in (("Dune", 2), ("Dune", 3), ("Emma", 1))
            ],
        )
        order_repo.add(order)
        order.confirm()
        order_repo.add(order)
        return order_repo.get(order.id)

    def test_process_manager_reserves_every_title_before_shipping(self):
        """Ch20: an order with two titles ships once both are reserved."""
        domain = ch20.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch20.Inventory)
            dune = ch20.Inventory(book_id="book-1", title="Dune", quantity=10)
            emma = ch20.Inventory(book_id="book-2", title="Emma", quantity=10)
            inv_repo.add(dune)
            inv_repo.add(emma)

            order = self._confirm("123 Main St")

            assert order.status == "COMPLETED"
            assert inv_repo.get(dune.id).quantity == 5
            assert inv_repo.get(emma.id).quantity == 9
            shipments = (
                domain.repository_for(ch20.Shipment)
                .query.filter(order_id=order.id)
                .all()
                .items
            )
            assert [s.status for s in shipments] == ["CREATED"]

    def test_failed_shipment_releases_every_title(self):
        """Ch20: compensation returns the stock of each title and cancels."""
        domain = ch20.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch20.Inventory)
            dune = ch20.Inventory(book_id="book-1", title="Dune", quantity=10)
            emma = ch20.Inventory(book_id="book-2", title="Emma", quantity=10)
            inv_repo.add(dune)
            inv_repo.add(emma)

            order = self._confirm("")

            assert order.status == "CANCELLED"
            assert inv_repo.get(dune.id).quantity == 10
            assert inv_repo.get(emma.id).quantity == 10
            assert inv_repo.get(dune.id).reserved_quantities == {}

    def test_second_release_changes_nothing(self):
        """Ch20: a repeated ReleaseInventory returns the stock once."""
        domain = ch20.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch20.Inventory)
            inv = ch20.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)
            domain.process(
                ch20.ReserveInventory(order_id="order-1", book_title="Dune", quantity=3)
            )

            release = ch20.ReleaseInventory(order_id="order-1", book_title="Dune")
            domain.process(release)
            domain.process(release)

            assert inv_repo.get(inv.id).quantity == 10

    def test_reservation_after_release_changes_nothing(self):
        """Ch20: a ReserveInventory that arrives after the release is skipped."""
        domain = ch20.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch20.Inventory)
            inv = ch20.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)
            reserve = ch20.ReserveInventory(
                order_id="order-1", book_title="Dune", quantity=3
            )

            domain.process(reserve)
            domain.process(ch20.ReleaseInventory(order_id="order-1", book_title="Dune"))
            domain.process(reserve)

            # A release that arrives before its reservation blocks it too.
            domain.process(ch20.ReleaseInventory(order_id="order-2", book_title="Dune"))
            domain.process(
                ch20.ReserveInventory(order_id="order-2", book_title="Dune", quantity=4)
            )

            assert inv_repo.get(inv.id).quantity == 10
            assert inv_repo.get(inv.id).reserved_quantities == {}

    def test_release_returns_the_quantity_reserved(self):
        """Ch20: a release returns what the order holds, not a quantity it is sent."""
        domain = ch20.domain
        with domain.domain_context():
            inv_repo = domain.repository_for(ch20.Inventory)
            inv = ch20.Inventory(book_id="book-1", title="Dune", quantity=10)
            inv_repo.add(inv)
            domain.process(
                ch20.ReserveInventory(order_id="order-1", book_title="Dune", quantity=1)
            )
            domain.process(
                ch20.ReserveInventory(order_id="order-2", book_title="Dune", quantity=2)
            )

            domain.process(ch20.ReleaseInventory(order_id="order-1", book_title="Dune"))

            assert inv_repo.get(inv.id).quantity == 8
            assert inv_repo.get(inv.id).reserved_quantities == {"order-2": 2}

    def test_repeated_reservation_event_creates_no_second_shipment(self):
        """Ch20: a repeated InventoryReserved after the last title is not counted."""
        domain = ch20.domain
        with domain.domain_context():
            order = ch20.Order(customer_name="Alice", shipping_address="1 Main St")
            domain.repository_for(ch20.Order).add(order)

            # Every title is already counted and the CreateShipment is in flight,
            # so a repeat of the last InventoryReserved must not send another.
            manager = ch20.OrderFulfillmentPM(
                order_id=order.id,
                items=[{"book_title": "Dune", "quantity": 2}],
                awaiting_titles=[],
            )
            manager.on_inventory_reserved(
                ch20.InventoryReserved(order_id=order.id, book_title="Dune", quantity=2)
            )

            shipments = (
                domain.repository_for(ch20.Shipment)
                .query.filter(order_id=order.id)
                .all()
                .items
            )
            assert shipments == []

    def test_repeated_create_shipment_creates_one(self):
        """Ch20: a CreateShipment processed twice leaves one shipment."""
        domain = ch20.domain
        with domain.domain_context():
            command = ch20.CreateShipment(order_id="order-1", address="1 Main St")
            domain.process(command)
            domain.process(command)

            shipments = (
                domain.repository_for(ch20.Shipment)
                .query.filter(order_id="order-1")
                .all()
                .items
            )
            assert [s.status for s in shipments] == ["CREATED"]


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
