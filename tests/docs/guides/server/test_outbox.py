"""The examples on the outbox guide behave as the page says."""

import pytest

from protean.server import Engine
from protean.utils.outbox import OutboxStatus
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _place_order(example, order_id: str) -> None:
    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(order_id=order_id, total=25.0), asynchronous=False
        )


def test_the_event_waits_in_the_outbox_until_the_engine_publishes_it():
    example = load_example("guides/server/outbox/001.py")
    example.domain.init(traverse=False)

    _place_order(example, "order-1")

    with example.domain.domain_context():
        rows = example.domain._get_outbox_repo("default").query.all().items
        assert [(row.stream_name, row.status) for row in rows] == [
            ("shop::order-order-1", OutboxStatus.PENDING.value)
        ]
        broker = example.domain.brokers["default"]
        assert broker.read("shop::order", "probe", 10) == []

    Engine(example.domain, test_mode=True).run()

    with example.domain.domain_context():
        rows = example.domain._get_outbox_repo("default").query.all().items
        assert [row.status for row in rows] == [OutboxStatus.PUBLISHED.value]
        published = broker.read("shop::order", "probe", 10)
        assert len(published) == 1
        _, payload = published[0]
        assert payload["data"]["order_id"] == "order-1"


def test_print_abandoned_lists_only_abandoned_rows(capsys):
    example = load_example("guides/server/outbox/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")
    _place_order(example, "order-2")

    example.print_abandoned()
    assert capsys.readouterr().out == ""

    with example.domain.domain_context():
        repo = example.domain._get_outbox_repo("default")
        row = next(
            row
            for row in repo.query.all().items
            if row.stream_name == "shop::order-order-2"
        )
        row.mark_abandoned("broker rejected the message")
        repo.add(row)

    example.print_abandoned()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert "shop::order-order-2" in lines[0]
    assert "broker rejected the message" in lines[0]
    assert "shop::order-order-1" not in lines[0]
