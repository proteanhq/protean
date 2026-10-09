"""The examples on the error handling guide behave as the page says."""

import logging

import pytest

from protean.server import Engine
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _place_order_and_run(example, sku: str, quantity: int):
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        order = example.place_order(sku, quantity)
        # The memory event store reads through the active domain context.
        Engine(example.domain, test_mode=True).run()
    return order


def test_handle_error_alerts_ops_with_the_failing_message(caplog):
    example = load_example("guides/server/error-handling/001.py")
    example.warehouse.online = False

    with caplog.at_level(logging.ERROR, logger=example.logger.name):
        order = _place_order_and_run(example, "SKU-1", 2)

    assert example.alerts, "handle_error was not called"
    for failure, message in example.alerts:
        assert isinstance(failure, example.ExternalServiceUnavailable)
        assert message.data["order_id"] == order.id
        assert message.data["sku"] == "SKU-1"
    assert (
        "OrderEventHandler failed: ExternalServiceUnavailable: warehouse API timed out"
        in caplog.messages
    )
    assert example.warehouse.reserved == []


def test_handle_error_logs_other_failures_without_alerting(caplog):
    example = load_example("guides/server/error-handling/001.py")

    with caplog.at_level(logging.ERROR, logger=example.logger.name):
        _place_order_and_run(example, "SKU-1", 0)

    assert example.alerts == []
    assert "OrderEventHandler failed: ValueError: cannot reserve 0 of SKU-1" in (
        caplog.messages
    )


def test_a_successful_handler_never_reaches_handle_error(caplog):
    example = load_example("guides/server/error-handling/001.py")

    with caplog.at_level(logging.ERROR, logger=example.logger.name):
        _place_order_and_run(example, "SKU-1", 2)

    assert example.warehouse.reserved == ["SKU-1"]
    assert example.alerts == []
    assert not [m for m in caplog.messages if "OrderEventHandler failed" in m]


def test_each_failure_in_an_exception_group_is_alerted_and_logged(caplog):
    example = load_example("guides/server/error-handling/001.py")
    group = ExceptionGroup(
        "two methods failed",
        [
            example.ExternalServiceUnavailable("warehouse API timed out"),
            ValueError("bad quantity"),
        ],
    )

    with caplog.at_level(logging.ERROR, logger=example.logger.name):
        example.OrderEventHandler.handle_error(group, "the message")

    assert [(type(f).__name__, m) for f, m in example.alerts] == [
        ("ExternalServiceUnavailable", "the message")
    ]
    assert caplog.messages == [
        (
            "OrderEventHandler failed: ExternalServiceUnavailable: warehouse API "
            "timed out; ValueError: bad quantity"
        )
    ]
