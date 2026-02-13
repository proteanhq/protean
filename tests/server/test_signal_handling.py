import asyncio
import signal
from unittest.mock import Mock, patch

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier
from protean.server.engine import Engine
from protean.utils import Processing
from protean.utils.mixins import handle


class User(BaseAggregate):
    user_id = Identifier(identifier=True)


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


class UserEventHandler(BaseEventHandler):
    @handle(UserLoggedIn)
    def count_users(self, event: UserLoggedIn) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(User, stream_category="authentication")
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.register(UserEventHandler, stream_category="authentication")
    test_domain.init(traverse=False)


class TestSignalHandling:
    """Test signal handling functionality across different platforms."""

    def test_signal_handlers_initialization(self, test_domain):
        """Test that signal handlers are properly initialized."""
        engine = Engine(domain=test_domain)
        assert hasattr(engine, "_original_signal_handlers")
        assert isinstance(engine._original_signal_handlers, dict)

    @patch("platform.system")
    def test_windows_signal_handling_setup(self, mock_platform, test_domain):
        """Test signal handler setup on Windows platform."""
        mock_platform.return_value = "Windows"

        with patch("signal.signal") as mock_signal:
            engine = Engine(domain=test_domain)
            engine._setup_signal_handlers()

            # Should call signal.signal for each signal
            assert mock_signal.call_count >= 3  # SIGHUP, SIGTERM, SIGINT

    @patch("platform.system")
    def test_unix_signal_handling_setup(self, mock_platform, test_domain):
        """Test signal handler setup on Unix-like platforms."""
        mock_platform.return_value = "Linux"

        engine = Engine(domain=test_domain)

        with patch.object(engine.loop, "add_signal_handler") as mock_add_handler:
            engine._setup_signal_handlers()

            # Should call add_signal_handler for each signal
            assert mock_add_handler.call_count >= 3  # SIGHUP, SIGTERM, SIGINT

    @patch("platform.system")
    def test_windows_signal_cleanup(self, mock_platform, test_domain):
        """Test signal handler cleanup on Windows platform."""
        mock_platform.return_value = "Windows"

        engine = Engine(domain=test_domain)

        # Mock original signal handlers
        engine._original_signal_handlers = {
            signal.SIGINT: Mock(),
            signal.SIGTERM: Mock(),
        }

        with patch("signal.signal") as mock_signal:
            engine._cleanup_signal_handlers()

            # Should restore original handlers
            assert mock_signal.call_count == 2

    @patch("platform.system")
    def test_unix_signal_cleanup(self, mock_platform, test_domain):
        """Test signal handler cleanup on Unix-like platforms."""
        mock_platform.return_value = "Linux"

        engine = Engine(domain=test_domain)

        with patch.object(engine.loop, "remove_signal_handler") as mock_remove_handler:
            engine._cleanup_signal_handlers()

            # Should remove signal handlers
            assert mock_remove_handler.call_count >= 3

    @patch("platform.system")
    def test_signal_handler_exception_handling(self, mock_platform, test_domain):
        """Test that signal handler setup handles exceptions gracefully."""
        mock_platform.return_value = "Windows"

        def signal_side_effect(*args):
            raise OSError("Signal not available")

        with patch("signal.signal", side_effect=signal_side_effect):
            engine = Engine(domain=test_domain)
            # Should not raise exception
            try:
                engine._setup_signal_handlers()
                # Should complete without raising exception
            except Exception as e:
                pytest.fail(
                    f"_setup_signal_handlers should handle signal exceptions gracefully: {e}"
                )

    @patch("platform.system")
    def test_windows_signal_handler_callback(self, mock_platform, test_domain):
        """Test that Windows signal handler callback works correctly."""
        mock_platform.return_value = "Windows"

        engine = Engine(domain=test_domain, test_mode=True)

        # Mock asyncio.run_coroutine_threadsafe to verify it gets called
        coroutine_called = False

        def mock_run_coroutine_threadsafe(coro, loop):
            nonlocal coroutine_called
            coroutine_called = True
            # Just close the coroutine without actually running it
            coro.close()
            return Mock()

        # Capture the signal handler that gets registered
        captured_handler = None

        def mock_signal_func(sig, handler):
            nonlocal captured_handler
            if sig == signal.SIGTERM:  # Capture only SIGTERM handler for testing
                captured_handler = handler
            return Mock()

        with patch(
            "asyncio.run_coroutine_threadsafe",
            side_effect=mock_run_coroutine_threadsafe,
        ):
            with patch("signal.signal", side_effect=mock_signal_func):
                engine._setup_signal_handlers()

                # Simulate signal reception when the loop is "running"
                if captured_handler:
                    # Mock that the loop is running
                    with patch.object(engine.loop, "is_running", return_value=True):
                        captured_handler(signal.SIGTERM)

        assert coroutine_called

    def test_signal_attribute_access_in_shutdown(self, test_domain):
        """Test that shutdown handles signal objects without 'name' attribute."""
        engine = Engine(domain=test_domain)

        # Test with a signal that has a name attribute
        with patch.object(engine, "shutting_down", True):
            try:
                asyncio.run(engine.shutdown(signal=signal.SIGTERM))
                # Should not raise exception
            except Exception as e:
                pytest.fail(
                    f"shutdown should handle signals with name attribute gracefully: {e}"
                )

        # Test with a signal-like object without name attribute
        class MockSignal:
            pass

        mock_signal = MockSignal()
        with patch.object(engine, "shutting_down", True):
            try:
                asyncio.run(engine.shutdown(signal=mock_signal))
                # Should not raise exception
            except Exception as e:
                pytest.fail(
                    f"shutdown should handle signals without name attribute gracefully: {e}"
                )

    @patch("platform.system")
    def test_fallback_when_add_signal_handler_not_available(
        self, mock_platform, test_domain
    ):
        """Test fallback to signal.signal when add_signal_handler is not available."""
        mock_platform.return_value = "Linux"  # Normally would use add_signal_handler

        engine = Engine(domain=test_domain)

        # Mock the condition directly in the engine method
        original_setup = engine._setup_signal_handlers

        def mock_setup():
            # Force the Windows path by mocking hasattr to return False
            original_hasattr = hasattr

            def mock_hasattr(obj, name):
                if name == "add_signal_handler" and obj is engine.loop:
                    return False
                return original_hasattr(obj, name)

            import builtins

            builtins.hasattr = mock_hasattr
            try:
                original_setup()
            finally:
                builtins.hasattr = original_hasattr

        with patch("signal.signal") as mock_signal:
            try:
                mock_setup()
                # Should complete without raising exception
            except Exception as e:
                pytest.fail(
                    f"signal handler setup should work with fallback gracefully: {e}"
                )

            # Should fall back to signal.signal
            assert mock_signal.call_count >= 3

    def test_cleanup_during_shutdown(self, test_domain):
        """Test that signal handlers are cleaned up during shutdown."""
        engine = Engine(domain=test_domain)

        cleanup_called = False
        original_cleanup = engine._cleanup_signal_handlers

        def mock_cleanup():
            nonlocal cleanup_called
            cleanup_called = True
            original_cleanup()

        engine._cleanup_signal_handlers = mock_cleanup

        # Run shutdown
        try:
            asyncio.run(engine.shutdown())
            # Should complete without raising exception
        except Exception as e:
            pytest.fail(f"shutdown should handle signal cleanup gracefully: {e}")

        assert cleanup_called

    def test_cleanup_during_run_finally_block(self, test_domain):
        """Test that signal handlers are cleaned up in the finally block of run()."""
        engine = Engine(domain=test_domain, test_mode=True)

        cleanup_called = False
        original_cleanup = engine._cleanup_signal_handlers

        def mock_cleanup():
            nonlocal cleanup_called
            cleanup_called = True
            original_cleanup()

        engine._cleanup_signal_handlers = mock_cleanup

        # Run the engine (will exit immediately due to no subscriptions)
        try:
            engine.run()
            # Should complete without raising exception
        except Exception as e:
            pytest.fail(f"engine.run() should handle signal cleanup gracefully: {e}")

        assert cleanup_called

    @patch("platform.system")
    def test_debug_logging_for_signal_setup(self, mock_platform, test_domain, caplog):
        """Test that debug logging works for signal setup."""
        mock_platform.return_value = "Windows"

        engine = Engine(domain=test_domain, debug=True)

        with caplog.at_level("DEBUG"):
            try:
                engine._setup_signal_handlers()
                # Should complete without raising exception
            except Exception as e:
                pytest.fail(
                    f"_setup_signal_handlers should handle debug logging gracefully: {e}"
                )

            assert any(
                "Using signal.signal() for signal handling" in record.message
                for record in caplog.records
            )

    @patch("platform.system")
    def test_unavailable_signal_handling(self, mock_platform, test_domain, caplog):
        """Test handling of unavailable signals."""
        mock_platform.return_value = "Windows"

        def signal_side_effect(sig, handler):
            if sig == signal.SIGHUP:
                raise OSError("Signal not available on this platform")
            return Mock()

        engine = Engine(domain=test_domain, debug=True)

        with patch("signal.signal", side_effect=signal_side_effect):
            with caplog.at_level("DEBUG"):
                try:
                    engine._setup_signal_handlers()
                    # Should complete without raising exception
                except Exception as e:
                    pytest.fail(
                        f"_setup_signal_handlers should handle unavailable signals gracefully: {e}"
                    )

                # Should log that SIGHUP is not available
                assert any(
                    "Signal" in record.message and "not available" in record.message
                    for record in caplog.records
                )

    @patch("platform.system")
    def test_unix_signal_handler_callback_triggers_shutdown(
        self, mock_platform, test_domain
    ):
        """Test that Unix signal handler callback calls loop.call_soon_threadsafe."""
        mock_platform.return_value = "Linux"

        engine = Engine(domain=test_domain, test_mode=True)

        # Capture the callbacks passed to add_signal_handler
        captured_callbacks = {}

        def mock_add_handler(sig, callback):
            captured_callbacks[sig] = callback

        with patch.object(
            engine.loop, "add_signal_handler", side_effect=mock_add_handler
        ):
            engine._setup_signal_handlers()

        # Verify callback was captured for SIGTERM
        assert signal.SIGTERM in captured_callbacks

        # Call the captured callback and verify it triggers call_soon_threadsafe
        with patch.object(engine.loop, "call_soon_threadsafe") as mock_call_soon:
            captured_callbacks[signal.SIGTERM]()
            mock_call_soon.assert_called_once()

    @patch("platform.system")
    def test_unix_signal_handler_skips_when_shutting_down(
        self, mock_platform, test_domain
    ):
        """Test that Unix signal handler callback skips when already shutting down."""
        mock_platform.return_value = "Linux"

        engine = Engine(domain=test_domain, test_mode=True)

        captured_callbacks = {}

        def mock_add_handler(sig, callback):
            captured_callbacks[sig] = callback

        with patch.object(
            engine.loop, "add_signal_handler", side_effect=mock_add_handler
        ):
            engine._setup_signal_handlers()

        # Set shutting_down before calling callback
        engine.shutting_down = True

        with patch.object(engine.loop, "call_soon_threadsafe") as mock_call_soon:
            captured_callbacks[signal.SIGTERM]()
            # Should NOT trigger call_soon_threadsafe when already shutting down
            mock_call_soon.assert_not_called()

    @patch("platform.system")
    def test_unix_signal_setup_handles_oserror(
        self, mock_platform, test_domain, caplog
    ):
        """Test that Unix signal handler setup handles OSError gracefully."""
        mock_platform.return_value = "Linux"

        engine = Engine(domain=test_domain, debug=True)

        def add_handler_side_effect(sig, callback):
            raise OSError("Signal not available on this platform")

        with patch.object(
            engine.loop,
            "add_signal_handler",
            side_effect=add_handler_side_effect,
        ):
            with caplog.at_level("DEBUG"):
                engine._setup_signal_handlers()

        assert any("not available" in record.message for record in caplog.records)

    @patch("platform.system")
    def test_windows_signal_cleanup_handles_oserror(self, mock_platform, test_domain):
        """Test that Windows signal cleanup handles OSError gracefully."""
        mock_platform.return_value = "Windows"

        engine = Engine(domain=test_domain)

        engine._original_signal_handlers = {
            signal.SIGINT: Mock(),
            signal.SIGTERM: Mock(),
        }

        with patch("signal.signal", side_effect=OSError("Cannot restore")):
            # Should not raise - errors are silently ignored during cleanup
            engine._cleanup_signal_handlers()

    @patch("platform.system")
    def test_unix_signal_cleanup_handles_oserror(self, mock_platform, test_domain):
        """Test that Unix signal cleanup handles OSError gracefully."""
        mock_platform.return_value = "Linux"

        engine = Engine(domain=test_domain)

        with patch.object(
            engine.loop,
            "remove_signal_handler",
            side_effect=OSError("Cannot remove"),
        ):
            # Should not raise - errors are silently ignored during cleanup
            engine._cleanup_signal_handlers()

    @patch("platform.system")
    def test_windows_signal_handler_skips_when_shutting_down(
        self, mock_platform, test_domain
    ):
        """Test that Windows signal handler skips when already shutting down."""
        mock_platform.return_value = "Windows"

        engine = Engine(domain=test_domain, test_mode=True)

        # Capture the signal handler
        captured_handler = None

        def mock_signal_func(sig, handler):
            nonlocal captured_handler
            if sig == signal.SIGTERM:
                captured_handler = handler
            return Mock()

        with patch("signal.signal", side_effect=mock_signal_func):
            engine._setup_signal_handlers()

        # Set shutting_down before calling callback
        engine.shutting_down = True

        with patch("asyncio.run_coroutine_threadsafe") as mock_run_coroutine:
            with patch.object(engine.loop, "is_running", return_value=True):
                if captured_handler:
                    captured_handler(signal.SIGTERM)
                # Should NOT call run_coroutine_threadsafe when shutting down
                mock_run_coroutine.assert_not_called()
