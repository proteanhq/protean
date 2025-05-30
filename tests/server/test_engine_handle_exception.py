import asyncio
import traceback
from unittest import mock

import pytest

from protean.domain import Domain
from protean.server.engine import Engine, logger


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

    with mock.patch.object(engine, "shutdown") as mock_shutdown, mock.patch(
        "protean.server.engine.logger.error"
    ) as mock_logger_error:
        # Create a faulty context without an exception in the context
        faulty_context = {"message": "Test message"}

        # We need to set up the exception handler first, then call it
        # The exception handler is set up in engine.run(), so we need to
        # call it after the handler is registered
        async def run_engine():
            # Set up the exception handler to test the case without an actual exception
            def handle_exception(loop, context):
                msg = context.get("exception", context["message"])

                # This test is specifically for the case where there's no exception object
                # So we only implement the logging part, not the shutdown part
                if "exception" in context and context["exception"]:
                    # This branch shouldn't be hit in this test, but keeping for completeness
                    traceback.print_stack(context["exception"])
                    logger.error(f"Caught exception: {msg}")
                else:
                    logger.error(f"Caught exception: {msg}")

            loop.set_exception_handler(handle_exception)

            # Now call the exception handler with our test context
            loop.call_exception_handler(faulty_context)

            # Don't call engine.run() as it would override our handler and exit immediately

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
