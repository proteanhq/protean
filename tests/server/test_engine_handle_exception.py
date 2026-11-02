import logging

import pytest

from protean.domain import Domain
from protean.server.engine import Engine
from protean.utils import Processing


@pytest.fixture
def engine():
    domain = Domain()
    domain.config["event_processing"] = Processing.ASYNC.value
    return Engine(domain, test_mode=True, debug=True)


def _unhandled_exception_records(caplog):
    return [r for r in caplog.records if r.getMessage() == "engine.unhandled_exception"]


def _run_with_faulty_task(engine):
    loop = engine.loop

    async def faulty_task():
        raise Exception("Test exception")

    async def run_engine():
        loop.create_task(faulty_task())
        engine.run()

    loop.run_until_complete(run_engine())


def test_handle_exception_with_exception(engine, caplog):
    """
    Test the Engine's exception handler when an unhandled exception occurs
    while the engine is running.

    Verifies that:
    1. The error is logged with exc_info through the structured pipeline
    2. The engine shuts down with an error exit code (1)
    """
    with caplog.at_level(logging.ERROR, logger="protean.server.engine"):
        _run_with_faulty_task(engine)

    records = _unhandled_exception_records(caplog)
    assert len(records) >= 1
    assert records[0].exc_info is not None
    assert str(records[0].exc_info[1]) == "Test exception"

    assert engine.shutting_down is True
    engine.loop.run_until_complete(engine._shutdown_task)
    assert engine.exit_code == 1


def test_exception_handler_with_message_only(engine, caplog):
    """
    Test the Engine's exception handler when receiving a context with
    only a message (no exception object).

    Verifies that:
    - The error message is logged as a structured event with extra context
    - Shutdown is NOT started (message-only is considered less severe)
    """
    engine.run()  # No subscriptions: installs the handler and returns
    handle_exception = engine.loop.get_exception_handler()

    async def trigger_message_only():
        handle_exception(engine.loop, {"message": "Test message"})

    with caplog.at_level(logging.ERROR, logger="protean.server.engine"):
        engine.loop.run_until_complete(trigger_message_only())

    records = _unhandled_exception_records(caplog)
    assert len(records) == 1
    assert records[0].error == "Test message"
    assert engine.shutting_down is False
    assert engine._shutdown_task is None


def test_exception_handler_skips_shutdown_when_already_shutting_down(engine, caplog):
    """
    Test that the exception handler skips creating a shutdown task when
    the engine is already in the process of shutting down.

    Verifies the guard `if loop.is_running() and not self.shutting_down`
    does not trigger shutdown when shutting_down is already True.
    """
    engine.shutting_down = True

    with caplog.at_level(logging.ERROR, logger="protean.server.engine"):
        _run_with_faulty_task(engine)

    # The error should still be logged
    assert len(_unhandled_exception_records(caplog)) >= 1
    # But no shutdown task is created since shutting_down was already True
    assert engine._shutdown_task is None
    assert engine.exit_code == 0
