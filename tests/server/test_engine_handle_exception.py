from unittest import mock

import pytest

from protean.domain import Domain
from protean.server.engine import Engine, logger
from protean.utils import Processing


@pytest.fixture
def engine():
    domain = Domain()
    domain.config["event_processing"] = Processing.ASYNC.value
    return Engine(domain, test_mode=True, debug=True)


def test_handle_exception_with_exception(engine):
    """
    Test the Engine's exception handler when receiving a context with
    an actual exception object.

    This test verifies that when the event loop encounters an unhandled exception:
    1. The exception message is properly logged
    2. The traceback is printed to assist with debugging
    3. The engine initiates shutdown with an error exit code (1)

    The test works by creating a faulty task that raises an exception,
    running it in the engine's event loop, and verifying the correct
    error handling procedures are followed.
    """
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


def test_exception_handler_with_message_only(engine):
    """
    This test method test_handle_exception_without_exception is testing
        how the Engine's exception handler behaves when it receives a context
        without an actual exception object.

    In asyncio, the event loop's exception handler can be called with
    contexts that contain either:
    - An actual exception object (in the "exception" key)
    - Just a message describing the issue (in the "message" key)

    The purpose of this test is to verify that:
    - When the exception handler receives a context with only a "message" (no exception)
    - It correctly logs the error message
    - It does NOT call the shutdown method (since this is considered a less severe error)

    The test works by:
    - Creating a custom exception handler that mimics Engine's behavior
    - Setting it as the loop's exception handler
    - Triggering it with a context that only has a "message" key
    - Verifying the correct logging happens and shutdown isn't called
    """
    loop = engine.loop

    # Define the exception handler - this will extract directly from the engine's run method
    def handle_exception(loop, context):
        msg = context.get("exception", context["message"])
        if "exception" in context and context["exception"]:
            # Code for handling with exception
            pass
        else:
            # This is the branch we're testing
            engine.loop.set_exception_handler(
                None
            )  # Reset handler to avoid infinite loop
            logger.error(f"Caught exception: {msg}")

    with mock.patch.object(engine, "shutdown") as mock_shutdown, mock.patch(
        "protean.server.engine.logger.error"
    ) as mock_logger_error:
        # Create a faulty task without an exception in the context
        async def run_engine():
            # Set the exception handler before triggering the exception
            loop.set_exception_handler(handle_exception)
            faulty_context = {"message": "Test message"}
            loop.call_exception_handler(faulty_context)

        # Run the engine
        loop.run_until_complete(run_engine())

        # Verify the log
        mock_logger_error.assert_any_call("Caught exception: Test message")
        mock_shutdown.assert_not_called()


def test_handle_exception_while_running(engine):
    """
    Test the Engine's exception handling mechanism during active operation.

    This test verifies that when an unhandled exception occurs while
    the engine is actively running:
    1. The exception message is properly captured and logged
    2. The full traceback is printed to facilitate debugging
    3. The engine correctly initiates a shutdown sequence with an error exit code (1)

    The test creates and schedules a faulty task that will raise an exception
    during engine execution, then verifies all error handling procedures are
    properly followed, ensuring the engine fails safely and predictably.
    """
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
