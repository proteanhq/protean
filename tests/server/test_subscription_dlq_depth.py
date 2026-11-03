"""Tests for the DLQ depth of event-store subscriptions.

An event-store subscription's dead-letter queue is the set of positions whose
latest record in its ``failed-*`` stream is ``Exhausted``. Each test writes
those records straight to the in-memory event store and reads the depth through
``collect_subscription_statuses``.
"""

from __future__ import annotations

import logging
from unittest.mock import patch
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server.subscription.event_store_subscription import FailedPositionStatus
from protean.server.subscription_status import (
    SubscriptionStatus,
    collect_subscription_statuses,
)
from protean.utils import fqn
from protean.utils.dlq import command_dispatcher_fqn, failed_positions_stream
from protean.utils.mixins import handle
from tests.cli._envelope import assert_envelope

STATUS_LOGGER = "protean.server.subscription_status"

runner = CliRunner()


class Order(BaseAggregate):
    client_id = String()


class OrderPlaced(BaseEvent):
    order_id = Identifier(identifier=True)


class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)


class OrderNotifier(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


class OrderAuditor(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


class PlaceOrderHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        pass


def _write_record(
    store, failed_stream: str, position: int, status: FailedPositionStatus
) -> None:
    """Append one failed-position record, in the shape a subscription writes."""
    store._write(
        failed_stream,
        status.value,
        {"position": position, "message_id": str(uuid4()), "retry_count": 1},
        metadata={
            "headers": {"id": str(uuid4()), "type": status.value},
            "domain": {"kind": "read_position"},
        },
    )


def _write_events(store, stream_category: str, count: int) -> None:
    metadata = {"headers": {"id": str(uuid4()), "type": "OrderPlaced"}}
    for n in range(count):
        store._write(f"{stream_category}-1", "OrderPlaced", {"n": n}, metadata)


def _statuses(domain: Domain) -> dict[str, SubscriptionStatus]:
    return {status.name: status for status in collect_subscription_statuses(domain)}


class TestEventStoreDlqDepth:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderNotifier, part_of=Order)
        test_domain.init(traverse=False)
        self.store = test_domain.event_store.store
        self.category = Order.meta_.stream_category
        self.failed_stream = failed_positions_stream(fqn(OrderNotifier), self.category)
        # Events in the category give the row a real lag and status.
        _write_events(self.store, self.category, 3)

    def test_one_exhausted_position_is_counted(self, test_domain):
        _write_record(self.store, self.failed_stream, 1, FailedPositionStatus.FAILED)
        _write_record(self.store, self.failed_stream, 1, FailedPositionStatus.EXHAUSTED)

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.dlq_depth == 1
        assert status.status != "unknown"

    @pytest.mark.parametrize(
        "later",
        [
            FailedPositionStatus.RESOLVED,
            FailedPositionStatus.PURGED,
            FailedPositionStatus.FAILED,
        ],
    )
    def test_a_later_record_clears_the_position(self, test_domain, later):
        _write_record(self.store, self.failed_stream, 1, FailedPositionStatus.EXHAUSTED)
        _write_record(self.store, self.failed_stream, 1, later)

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.dlq_depth == 0

    def test_depth_counts_positions_not_records(self, test_domain):
        for position in (1, 2):
            _write_record(
                self.store, self.failed_stream, position, FailedPositionStatus.FAILED
            )
            _write_record(
                self.store, self.failed_stream, position, FailedPositionStatus.FAILED
            )
            _write_record(
                self.store,
                self.failed_stream,
                position,
                FailedPositionStatus.EXHAUSTED,
            )
        _write_record(self.store, self.failed_stream, 2, FailedPositionStatus.RESOLVED)

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.dlq_depth == 1

    def test_missing_failed_stream_is_zero(self, test_domain):
        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.dlq_depth == 0
        assert status.status != "unknown"

    def test_failed_stream_read_failure_keeps_the_row(self, test_domain, caplog):
        _write_record(self.store, self.failed_stream, 1, FailedPositionStatus.EXHAUSTED)
        real_read_all = self.store.read_all

        def read_all(stream_name, *args, **kwargs):
            if stream_name.startswith("failed-"):
                raise RuntimeError("failed stream unreadable")
            return real_read_all(stream_name, *args, **kwargs)

        with (
            patch.object(self.store, "read_all", side_effect=read_all),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.dlq_depth == 0
        assert status.lag == 4
        assert status.status == "lagging"
        assert (
            f"Could not read DLQ depth of {self.failed_stream}: "
            "RuntimeError('failed stream unreadable')"
        ) in caplog.messages


def test_command_dispatcher_row_counts_its_exhausted_positions(test_domain):
    test_domain.register(Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(PlaceOrderHandler, part_of=Order)
    test_domain.init(traverse=False)
    store = test_domain.event_store.store
    command_stream = f"{Order.meta_.stream_category}:command"
    failed_stream = failed_positions_stream(
        command_dispatcher_fqn(command_stream), command_stream
    )
    _write_record(store, failed_stream, 5, FailedPositionStatus.EXHAUSTED)

    status = _statuses(test_domain)[f"commands:{command_stream}"]

    assert status.dlq_depth == 1


def test_depth_matches_what_eventstore_dlq_list_reports(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(OrderNotifier, part_of=Order)
    test_domain.register(OrderAuditor, part_of=Order)
    test_domain.register(PlaceOrderHandler, part_of=Order)
    test_domain.init(traverse=False)
    store = test_domain.event_store.store
    category = Order.meta_.stream_category
    command_stream = f"{category}:command"

    notifier_stream = failed_positions_stream(fqn(OrderNotifier), category)
    for position in (1, 2, 3):
        _write_record(store, notifier_stream, position, FailedPositionStatus.EXHAUSTED)
    _write_record(store, notifier_stream, 2, FailedPositionStatus.PURGED)

    auditor_stream = failed_positions_stream(fqn(OrderAuditor), category)
    _write_record(store, auditor_stream, 1, FailedPositionStatus.EXHAUSTED)
    _write_record(store, auditor_stream, 1, FailedPositionStatus.RESOLVED)

    dispatcher_stream = failed_positions_stream(
        command_dispatcher_fqn(command_stream), command_stream
    )
    for position in (4, 6):
        _write_record(
            store, dispatcher_stream, position, FailedPositionStatus.EXHAUSTED
        )

    with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
        result = runner.invoke(
            app, ["eventstore", "dlq", "list", "--domain", "x.py", "--json"]
        )
    assert result.exit_code == 0, result.output
    listed = assert_envelope(result.stdout)["data"]["subscriptions"]
    assert listed, "the CLI listed no exhausted positions"
    listed_counts = {
        (sub["handler"], sub["stream_category"]): len(sub["exhausted"])
        for sub in listed
    }

    statuses = _statuses(test_domain)
    rows = {
        (fqn(OrderNotifier), category): statuses[fqn(OrderNotifier)],
        (fqn(OrderAuditor), category): statuses[fqn(OrderAuditor)],
        (command_dispatcher_fqn(command_stream), command_stream): statuses[
            f"commands:{command_stream}"
        ],
    }
    for identity, status in rows.items():
        assert status.dlq_depth == listed_counts.get(identity, 0), identity
    assert listed_counts == {
        (fqn(OrderNotifier), category): 2,
        (command_dispatcher_fqn(command_stream), command_stream): 2,
    }
