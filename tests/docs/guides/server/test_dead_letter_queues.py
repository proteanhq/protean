"""The examples on the dead letter queues guide behave as the page says."""

import pytest

from protean.server import Engine
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

DLQ_STREAM = "library::book:dlq"


def _add_books_and_run(example) -> None:
    # The maintenance task sleeps a full check interval before it sees the
    # shutdown, which would hold every engine run open for that long.
    example.domain.config["server"]["dlq"]["enabled"] = False
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.add_book(None)
        example.add_book("9780132350884")
    Engine(example.domain, test_mode=True).run()


def test_a_message_that_keeps_failing_lands_on_the_dlq_stream():
    example = load_example("guides/server/dead-letter-queues/001.py")

    _add_books_and_run(example)

    with example.domain.domain_context():
        entries = example.domain.brokers["default"].read(DLQ_STREAM, "probe", 10)

    # Only the book without an ISBN fails; the other one is handled.
    assert len(entries) == 1
    _, dlq_message = entries[0]
    assert dlq_message["data"]["isbn"] is None
    assert dlq_message["_dlq_metadata"]["original_stream"] == "library::book"
    assert dlq_message["_dlq_metadata"]["retry_count"] == 3
    assert dlq_message["_dlq_metadata"]["consumer_group"].endswith(".CatalogHandler")


def test_with_the_dlq_disabled_the_failed_message_is_dropped():
    example = load_example("guides/server/dead-letter-queues/001.py")
    example.domain.config["server"]["stream_subscription"]["enable_dlq"] = False

    _add_books_and_run(example)

    with example.domain.domain_context():
        entries = example.domain.brokers["default"].read(DLQ_STREAM, "probe", 10)
    assert entries == []


def test_the_engine_resolves_alert_callback_to_page_oncall():
    example = load_example("guides/server/dead-letter-queues/001.py")
    example.domain.init(traverse=False)

    engine = Engine(example.domain, test_mode=True)

    assert engine._dlq_maintenance is not None
    assert engine._dlq_maintenance.alert_callback is example.page_oncall
    assert engine._dlq_maintenance.alert_threshold == 50


def test_page_oncall_sends_one_warning_naming_the_stream_and_depth():
    example = load_example("guides/server/dead-letter-queues/001.py")

    example.page_oncall(dlq_stream=DLQ_STREAM, depth=73, threshold=50)

    assert example.sent_alerts == [
        {
            "summary": f"DLQ {DLQ_STREAM} has 73 entries (threshold 50)",
            "severity": "warning",
        }
    ]
