# --8<-- [start:full]
"""Chapter 15: Fact Events and the Reporting Pipeline

Demonstrates how fact events provide a snapshot of aggregate state after every
change.  Fact events are auto-generated when an aggregate is configured with
``fact_events=True``.  They flow through a separate ``<aggregate>-fact``
stream, making them ideal for building projections that only need the latest
state rather than reconstructing it from individual domain events.
"""

from protean import Domain, handle
from protean.fields import Float, Identifier, String, Text
from protean.utils.globals import current_domain

domain = Domain()
domain.config["event_processing"] = "sync"


@domain.event(part_of="Book")
class BookAdded:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price: Float()


# --8<-- [start:aggregate]
@domain.aggregate(fact_events=True)
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price: Float(default=0.0)
    description: Text()

    @classmethod
    def add_to_catalog(cls, title, author, isbn=None, price=0.0, description=""):
        book = cls(
            title=title,
            author=author,
            isbn=isbn,
            price=price,
            description=description,
        )
        book.raise_(
            BookAdded(
                book_id=book.id,
                title=book.title,
                author=book.author,
                price=price,
            )
        )
        return book

    def update_price(self, new_price: float):
        self.price = new_price


# --8<-- [end:aggregate]


# --8<-- [start:projection]
@domain.projection
class BookReport:
    """Marketing dashboard projection — populated from fact events.

    When running with ``protean server`` (async processing), the
    ``BookReportHandler`` below maintains this projection automatically.
    """

    book_id: Identifier(identifier=True, required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price: Float()
    isbn: String(max_length=13)


# --8<-- [end:projection]


# --8<-- [start:handler]
@domain.event_handler(part_of=Book)
class BookReportHandler:
    """Consumes fact events to maintain the BookReport projection.

    Each fact event contains the complete current state, so we simply
    overwrite the projection entry — no need to apply deltas.

    When running with async event processing (``protean server``), this
    handler is automatically subscribed to the ``<domain>::book-fact``
    stream and invoked for every fact event.
    """

    @handle("$any")
    def on_book_fact(self, event):
        # Only process fact events (ignore delta events like BookAdded)
        if not event.__class__.__name__.endswith("FactEvent"):
            return

        repo = current_domain.repository_for(BookReport)

        try:
            report = repo.get(event.id)
            report.title = event.title
            report.author = event.author
            report.price = event.price
            report.isbn = event.isbn or ""
        except Exception:
            report = BookReport(
                book_id=event.id,
                title=event.title,
                author=event.author,
                price=event.price,
                isbn=event.isbn or "",
            )

        repo.add(report)


# --8<-- [end:handler]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        book_repo = domain.repository_for(Book)

        # Add a book — triggers both the BookAdded event and a fact event
        print("=== Adding a Book ===")
        gatsby = Book.add_to_catalog(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            isbn="9780743273565",
            price=12.99,
        )
        book_repo.add(gatsby)

        # Update price — triggers a new fact event with complete state
        print("\n=== Updating Price ===")
        gatsby.update_price(15.99)
        book_repo.add(gatsby)

        # Read fact events from the event store
        fact_stream = f"{Book.meta_.stream_category}-fact-{gatsby.id}"
        fact_messages = domain.event_store.store.read(fact_stream)
        print(f"\nFact events in stream: {len(fact_messages)}")
        for msg in fact_messages:
            event = msg.to_domain_object()
            print(f"  Title: {event.title}, Price: ${event.price}")

        assert len(fact_messages) == 2  # One per state change
        last_fact = fact_messages[-1].to_domain_object()
        assert last_fact.price == 15.99
        assert last_fact.title == "The Great Gatsby"

        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
