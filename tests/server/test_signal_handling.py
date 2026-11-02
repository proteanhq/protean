import asyncio
import logging
import os
import signal
from unittest.mock import patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier
from protean.server.engine import Engine
from protean.utils import Processing
from protean.utils.mixins import handle

_SIGNALS = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)


class User(BaseAggregate):
    user_id: Identifier(identifier=True)


class UserLoggedIn(BaseEvent):
    user_id: Identifier(identifier=True)


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


@pytest.fixture(autouse=True)
def original_handlers():
    """Install a no-op handler for each signal and restore the real ones after.

    A test that sends itself a signal must not end the test run if the
    engine fails to install its own handler.
    """
    saved = {sig: signal.getsignal(sig) for sig in _SIGNALS}

    def ignore(signum, frame):
        pass

    for sig in _SIGNALS:
        signal.signal(sig, ignore)
    yield ignore
    for sig, handler in saved.items():
        signal.signal(sig, handler)


class _LoopWithoutSignalSupport:
    """An event loop with no ``add_signal_handler``.

    Every asyncio loop defines the method, so only a third-party loop can
    lack it.
    """

    def is_running(self) -> bool:
        return False


def _shutdown_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == "engine.shutting_down"]


def _send_sigterm_and_run(engine: Engine) -> None:
    """Send SIGTERM to this process from inside the engine's running loop.

    The loop runs until the engine's shutdown stops it. A stop scheduled after
    five seconds keeps a broken handler from hanging the test.
    """
    engine.loop.call_soon(os.kill, os.getpid(), signal.SIGTERM)
    engine.loop.call_later(5, engine.loop.stop)
    engine.loop.run_forever()


def _send_sigterm_and_settle(engine: Engine) -> None:
    """Send SIGTERM and give the loop a few iterations to react."""

    async def send() -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        for _ in range(5):
            await asyncio.sleep(0)

    engine.loop.run_until_complete(send())


class TestSignalHandling:
    """Test signal handling functionality across different platforms."""

    @patch("platform.system", return_value="Windows")
    def test_windows_cleanup_restores_original_handlers(
        self, mock_platform, test_domain
    ):
        engine = Engine(domain=test_domain)

        def original(signum, frame):
            pass

        engine._original_signal_handlers = {
            signal.SIGINT: original,
            signal.SIGTERM: original,
        }

        engine._cleanup_signal_handlers()

        assert signal.getsignal(signal.SIGINT) is original
        assert signal.getsignal(signal.SIGTERM) is original

    @patch("platform.system", return_value="Windows")
    def test_windows_signal_cleanup_handles_oserror(self, mock_platform, test_domain):
        """Errors restoring a handler are ignored during cleanup."""
        engine = Engine(domain=test_domain)
        engine._original_signal_handlers = {signal.SIGINT: signal.SIG_DFL}

        with patch("signal.signal", side_effect=OSError("Cannot restore")) as restore:
            engine._cleanup_signal_handlers()

        restore.assert_called_once_with(signal.SIGINT, signal.SIG_DFL)

    @patch("platform.system", return_value="Linux")
    def test_unix_signal_cleanup(self, mock_platform, test_domain, original_handlers):
        """Cleanup removes the loop's handlers, which puts the defaults back."""
        engine = Engine(domain=test_domain)
        engine._setup_signal_handlers()
        assert signal.getsignal(signal.SIGTERM) is not original_handlers

        engine._cleanup_signal_handlers()

        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

    @patch("platform.system", return_value="Linux")
    def test_unix_signal_cleanup_handles_oserror(self, mock_platform, test_domain):
        """Errors removing a handler are ignored during cleanup."""
        engine = Engine(domain=test_domain)

        with patch.object(
            engine.loop,
            "remove_signal_handler",
            side_effect=OSError("Cannot remove"),
        ) as remove:
            engine._cleanup_signal_handlers()

        assert remove.call_count == len(_SIGNALS)

    @patch("platform.system", return_value="Windows")
    def test_windows_signal_handler_callback(
        self, mock_platform, test_domain, original_handlers, caplog
    ):
        """On Windows the engine installs a handler for each signal with
        ``signal.signal``. A signal received while the loop runs shuts the
        engine down, and the shutdown restores the original handlers."""
        engine = Engine(domain=test_domain, test_mode=True)

        engine._setup_signal_handlers()

        assert set(engine._original_signal_handlers) == set(_SIGNALS)
        for sig in _SIGNALS:
            assert signal.getsignal(sig) is not original_handlers

        with caplog.at_level(logging.INFO, logger="protean.server.engine"):
            _send_sigterm_and_run(engine)

        assert engine.shutting_down is True
        records = _shutdown_records(caplog)
        assert len(records) == 1
        assert records[0].signal == str(int(signal.SIGTERM))
        assert signal.getsignal(signal.SIGTERM) is original_handlers

    @patch("platform.system", return_value="Windows")
    def test_windows_signal_handler_skips_when_shutting_down(
        self, mock_platform, test_domain, caplog
    ):
        engine = Engine(domain=test_domain, test_mode=True)
        engine._setup_signal_handlers()
        engine.shutting_down = True

        with caplog.at_level(logging.INFO, logger="protean.server.engine"):
            _send_sigterm_and_settle(engine)

        engine._cleanup_signal_handlers()
        assert _shutdown_records(caplog) == []

    @pytest.mark.parametrize("platform_name", ["Linux", "Windows"])
    def test_unavailable_signal_handling(
        self, test_domain, caplog, original_handlers, platform_name
    ):
        """A signal the platform cannot install is logged and skipped; the
        others are still installed."""
        engine = Engine(domain=test_domain, debug=True)
        install_signal = signal.signal

        def signal_side_effect(sig, handler):
            if sig == signal.SIGHUP:
                raise OSError("Signal not available on this platform")
            return install_signal(sig, handler)

        def add_handler_side_effect(sig, callback):
            raise OSError("Signal not available on this platform")

        with (
            patch("platform.system", return_value=platform_name),
            patch("signal.signal", side_effect=signal_side_effect),
            patch.object(
                engine.loop, "add_signal_handler", side_effect=add_handler_side_effect
            ),
            caplog.at_level(logging.DEBUG, logger="protean.server.engine"),
        ):
            engine._setup_signal_handlers()

        messages = [r.getMessage() for r in caplog.records]
        unavailable = [m for m in messages if "not available" in m]
        if platform_name == "Windows":
            assert (
                "Using signal.signal() for signal handling "
                "(Windows or unsupported platform)" in messages
            )
            assert len(unavailable) == 1
            assert signal.SIGHUP not in engine._original_signal_handlers
            assert signal.getsignal(signal.SIGTERM) is not original_handlers
        else:
            assert len(unavailable) == len(_SIGNALS)

    @pytest.mark.parametrize(
        "sig, name",
        [(signal.SIGTERM, "SIGTERM"), (15, "15"), (None, None)],
        ids=["signal", "number", "none"],
    )
    def test_shutdown_logs_the_signal_name(self, test_domain, caplog, sig, name):
        """Shutdown names a ``Signals`` member by name and anything else by
        its string form."""
        engine = Engine(domain=test_domain)

        with caplog.at_level(logging.INFO, logger="protean.server.engine"):
            asyncio.run(engine.shutdown(signal=sig))

        records = _shutdown_records(caplog)
        assert len(records) == 1
        assert records[0].signal == name

    @patch("platform.system", return_value="Linux")
    def test_fallback_when_add_signal_handler_not_available(
        self, mock_platform, test_domain, original_handlers, caplog
    ):
        """A loop without ``add_signal_handler`` falls back to ``signal.signal``
        even off Windows, and cleanup restores the original handlers."""
        engine = Engine(domain=test_domain, debug=True)
        engine.loop.close()
        engine.loop = _LoopWithoutSignalSupport()

        with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
            engine._setup_signal_handlers()

        assert set(engine._original_signal_handlers) == set(_SIGNALS)
        for sig in _SIGNALS:
            assert signal.getsignal(sig) is not original_handlers
        assert any(
            r.getMessage().startswith("Using signal.signal()") for r in caplog.records
        )

        engine._cleanup_signal_handlers()

        for sig in _SIGNALS:
            assert signal.getsignal(sig) is original_handlers

    def test_cleanup_during_shutdown(self, test_domain, original_handlers):
        """Shutdown removes the handlers the engine installed."""
        engine = Engine(domain=test_domain)
        engine._setup_signal_handlers()
        assert signal.getsignal(signal.SIGTERM) is not original_handlers

        asyncio.run(engine.shutdown())

        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL

    def test_cleanup_during_run_finally_block(self, test_domain):
        """run() removes the handlers it installed before it returns."""
        engine = Engine(domain=test_domain, test_mode=True)

        # The engine exits on its own in test mode.
        engine.run()

        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

    @patch("platform.system", return_value="Linux")
    def test_unix_signal_handler_callback_triggers_shutdown(
        self, mock_platform, test_domain, original_handlers, caplog
    ):
        """On Unix the engine installs each handler on the loop. A signal
        received while the loop runs shuts the engine down."""
        engine = Engine(domain=test_domain, test_mode=True)

        engine._setup_signal_handlers()

        for sig in _SIGNALS:
            assert signal.getsignal(sig) is not original_handlers

        with caplog.at_level(logging.INFO, logger="protean.server.engine"):
            _send_sigterm_and_run(engine)

        assert engine.shutting_down is True
        records = _shutdown_records(caplog)
        assert len(records) == 1
        assert records[0].signal == "SIGTERM"

    @patch("platform.system", return_value="Linux")
    def test_unix_signal_handler_skips_when_shutting_down(
        self, mock_platform, test_domain, caplog
    ):
        engine = Engine(domain=test_domain, test_mode=True)
        engine._setup_signal_handlers()
        engine.shutting_down = True

        with caplog.at_level(logging.INFO, logger="protean.server.engine"):
            _send_sigterm_and_settle(engine)

        engine._cleanup_signal_handlers()
        assert _shutdown_records(caplog) == []
