import asyncio
from unittest import mock

import pytest

from protean.domain import Domain
from protean.server.engine import Engine


@pytest.fixture
def engine():
    domain = Domain(__file__, load_toml=False)
    return Engine(domain, test_mode=True, debug=True)


def test_handle_exception_with_exception(engine):
    loop = engine.loop

    async def faulty_task():
        raise Exception("Test exception")

    with mock.patch.object(engine, "shutdown") as mock_shutdown, mock.patch(
        "traceback.print_stack"
    ) as mock_print_stack, mock.patch(
        "protean.server.engine.logger.error"
    ) as mock_logger_error:
        # Start the engine in a separate coroutine
        async def run_engine():
            loop.create_task(faulty_task())
            engine.run()

        # Run the engine and handle the exception
        loop.run_until_complete(run_engine())

        # Ensure the logger captured the exception message
        mock_logger_error.assert_any_call("Caught exception: Test exception")
        mock_print_stack.assert_called_once()
        mock_shutdown.assert_called_once_with(exit_code=1)


def test_handle_exception_without_exception(engine):
    loop = engine.loop

    async def faulty_task():
        raise Exception("Test exception without exception in context")

    with mock.patch.object(engine, "shutdown") as mock_shutdown, mock.patch(
        "protean.server.engine.logger.error"
    ) as mock_logger_error:
        # Create a faulty task without an exception in the context
        async def run_engine():
            faulty_context = {"message": "Test message"}
            loop.call_exception_handler(faulty_context)
            engine.run()

        # Run the engine
        loop.run_until_complete(run_engine())

        mock_logger_error.assert_any_call("Caught exception: Test message")
        mock_shutdown.assert_not_called()


def test_handle_exception_while_running(engine):
    loop = engine.loop

    async def faulty_task():
        raise Exception("Test exception while running")

    with mock.patch.object(engine, "shutdown") as mock_shutdown, mock.patch(
        "traceback.print_stack"
    ) as mock_print_stack, mock.patch(
        "protean.server.engine.logger.error"
    ) as mock_logger_error:
        # Run the engine with a faulty task that raises an exception
        async def run_engine():
            loop.create_task(faulty_task())
            engine.run()

        # Run the engine
        loop.run_until_complete(run_engine())

        mock_logger_error.assert_any_call(
            "Caught exception: Test exception while running"
        )
        mock_print_stack.assert_called_once()
        mock_shutdown.assert_called_once_with(exit_code=1)
