"""Tests for the Bookshelf tutorial source files (ch01-ch07).

Each test imports the actual chapter module from docs_src/ and exercises
its domain objects, commands, and assertions — the same logic as the
chapter's ``if __name__ == "__main__"`` block.

Runs with in-memory adapters by default.  Pass ``--db``, ``--store``,
and ``--broker`` to pytest to exercise real adapters (same flags used
by the rest of the test suite).
"""

import importlib.util
import os
import sys
import types

import pytest

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


# Load all 7 chapters at module level (each has its own Domain instance)
ch01 = _load_chapter(1)
ch02 = _load_chapter(2)
ch03 = _load_chapter(3)
ch04 = _load_chapter(4)
ch05 = _load_chapter(5)
ch06 = _load_chapter(6)
ch07 = _load_chapter(7)

# Chapters that have projections (need DB artifact create/drop with real DBs)
_HAS_PROJECTIONS = {ch07}


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
# PART II: Making It Event-Driven (Ch 5-6)
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
            inventories = domain.repository_for(ch06.Inventory)._dao.query.all()
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
# PART III: Read Models & Persistence (Ch 7)
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

            # Verify projection was populated
            all_entries = catalog_repo._dao.query.all()
            assert all_entries.total == 2

            # Update price — projector updates the catalog
            gatsby.update_price(15.99)
            book_repo.add(gatsby)

            updated = catalog_repo.get(gatsby.id)
            assert updated.price == 15.99
            assert updated.title == "The Great Gatsby"
