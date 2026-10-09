from protean import Domain, current_domain, handle
from protean.fields import Identifier, String

domain = Domain(
    name="Library",
    config={
        # The inline broker waits before it hands a failed message back. A zero
        # wait lets a test-mode engine run see every retry.
        "brokers": {"default": {"provider": "inline", "retry_delay": 0}},
        "server": {
            "default_subscription_type": "stream",
            "stream_subscription": {
                "max_retries": 3,
                "retry_delay_seconds": 0,
                "enable_dlq": True,
            },
            "dlq": {
                "enabled": True,
                "alert_threshold": 50,
                "alert_callback": f"{__name__}.page_oncall",
            },
        },
    },
)

sent_alerts: list[dict] = []


def send_pagerduty_event(summary: str, severity: str) -> None:
    sent_alerts.append({"summary": summary, "severity": severity})


# --8<-- [start:page_oncall]
# myapp/alerts.py
def page_oncall(dlq_stream: str, depth: int, threshold: int) -> None:
    send_pagerduty_event(
        summary=f"DLQ {dlq_stream} has {depth} entries (threshold {threshold})",
        severity="warning",
    )


# --8<-- [end:page_oncall]


@domain.aggregate
class Book:
    isbn: String(max_length=13)


@domain.event(part_of=Book)
class BookAdded:
    book_id: Identifier(required=True)
    isbn: String(max_length=13)


@domain.event_handler(part_of=Book)
class CatalogHandler:
    @handle(BookAdded)
    def on_book_added(self, event: BookAdded) -> None:
        # The bug the page describes: the handler expects an ISBN on every event.
        if event.isbn is None:
            raise KeyError("isbn")


def add_book(isbn: str | None) -> Book:
    book = Book(isbn=isbn)
    book.raise_(BookAdded(book_id=book.id, isbn=isbn))
    current_domain.repository_for(Book).add(book)
    return book
