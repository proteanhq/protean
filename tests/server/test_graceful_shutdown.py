"""Tests for graceful resource cleanup on Engine shutdown."""

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.utils.mixins import handle


class ShutdownUser(BaseAggregate):
    email: String()


class ShutdownUserRegistered(BaseEvent):
    user_id: Identifier()


class ShutdownUserHandler(BaseEventHandler):
    @handle(ShutdownUserRegistered)
    def on_registered(self, event: ShutdownUserRegistered) -> None:
        pass


@pytest.mark.no_test_domain
class TestDomainClose:
    """Test Domain.close() shuts down all infrastructure adapters."""

    def test_close_is_idempotent(self):
        """Calling close() multiple times should not raise."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        domain.close()
        domain.close()  # Should not raise

    def test_close_continues_on_adapter_error(self, caplog):
        """If one adapter's close() raises, others still get closed."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with (
            patch.object(
                domain.event_store,
                "close",
                side_effect=RuntimeError("connection lost"),
            ),
            patch.object(domain.brokers, "close") as mock_broker_close,
            caplog.at_level(logging.ERROR),
        ):
            domain.close()

        mock_broker_close.assert_called_once()
        assert any("Error closing event store" in r.message for r in caplog.records)

    def test_close_order_is_reverse_of_init(self):
        """close() closes each adapter once: event store first, providers last."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        call_order = []

        with (
            patch.object(
                domain.event_store,
                "close",
                side_effect=lambda: call_order.append("event_store"),
            ),
            patch.object(
                domain.brokers,
                "close",
                side_effect=lambda: call_order.append("brokers"),
            ),
            patch.object(
                domain.caches,
                "close",
                side_effect=lambda: call_order.append("caches"),
            ),
            patch.object(
                domain.providers,
                "close",
                side_effect=lambda: call_order.append("providers"),
            ),
        ):
            domain.close()

        assert call_order == ["event_store", "brokers", "caches", "providers"]


@pytest.mark.no_test_domain
class TestEngineShutdownOrder:
    """Test Engine.shutdown() calls domain.close() and follows correct ordering."""

    def test_shutdown_closes_domain_once_after_subscriptions(self):
        """Engine.shutdown() calls domain.close() once, after every
        subscription has stopped."""
        domain = Domain(name="Test")
        domain.register(ShutdownUser)
        domain.register(ShutdownUserRegistered, part_of=ShutdownUser)
        domain.register(ShutdownUserHandler, part_of=ShutdownUser)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            subscriptions = list(engine._subscriptions.values())
            assert subscriptions
            assert all(sub.keep_going for sub in subscriptions)

            still_running_at_close = []
            original_close = domain.close

            def tracked_close():
                still_running_at_close.append([sub.keep_going for sub in subscriptions])
                original_close()

            with patch.object(domain, "close", side_effect=tracked_close):
                engine.loop.run_until_complete(engine.shutdown())

            assert still_running_at_close == [[False] * len(subscriptions)]

    def test_shutdown_domain_close_error_does_not_prevent_loop_stop(self, caplog):
        """Even if domain.close() raises, the loop should still stop."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            with (
                patch.object(
                    domain, "close", side_effect=RuntimeError("cleanup failed")
                ),
                caplog.at_level(logging.ERROR),
            ):
                engine.loop.run_until_complete(engine.shutdown())

            assert any("engine.cleanup_failed" in r.message for r in caplog.records)


class TestConfigurableDrainWindow:
    """The drain window is read from [server].drain_timeout and governs the
    wait before in-flight tasks are force-cancelled on shutdown."""

    def _engine(self, drain_timeout=None):
        domain = Domain(name="Test")
        if drain_timeout is not None:
            domain.config["server"]["drain_timeout"] = drain_timeout
        domain.init(traverse=False)
        with domain.domain_context():
            return Engine(domain, test_mode=True)

    def _drain_with_inflight(self, engine, sleep_for):
        """Start an in-flight handler, run shutdown, report its fate."""
        state = {"completed": False, "cancelled": False}

        async def slow_handler():
            try:
                await asyncio.sleep(sleep_for)
                state["completed"] = True
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

        async def _run():
            task = asyncio.ensure_future(slow_handler())
            await engine.shutdown()
            return task

        engine.loop.run_until_complete(_run())
        return state

    @pytest.mark.parametrize("value, expected", [(None, 10.0), (3, 3.0)])
    def test_window_is_read_with_a_default_of_ten(self, value, expected):
        """With no key set, the drain window is 10; a set key is used as is."""
        engine = self._engine(drain_timeout=value)
        assert engine.drain_timeout == expected

    def test_short_window_cancels_straggler(self, caplog):
        """A configured 0.05s window force-cancels a 1s in-flight handler and
        logs the cancellation.

        This also proves the old hardcoded 10.0 literal is gone: under 10s the
        1s sleep would finish, so the task would complete, not cancel.
        """
        engine = self._engine(drain_timeout=0.05)
        with caplog.at_level(logging.DEBUG):
            state = self._drain_with_inflight(engine, sleep_for=1.0)
        assert state["cancelled"] is True
        assert state["completed"] is False
        assert any("engine.cancelling_tasks" in r.message for r in caplog.records)

    def test_generous_window_lets_inflight_finish(self):
        """A 2s window lets a 0.05s in-flight handler run to completion."""
        engine = self._engine(drain_timeout=2.0)
        # Assert the configured window is what governs the wait, so this does
        # not pass vacuously under the old hardcoded 10.0 (a 0.05s handler
        # finishes under any window, so completion alone proves nothing).
        assert engine.drain_timeout == 2.0
        state = self._drain_with_inflight(engine, sleep_for=0.05)
        assert state["completed"] is True
        assert state["cancelled"] is False

    @pytest.mark.parametrize(
        "value",
        [
            "not-a-number",
            True,
            False,
            float("nan"),
            float("inf"),
            float("-inf"),
            "nan",
            "inf",
            10**400,
        ],
    )
    def test_invalid_window_falls_back_to_ten_and_warns(self, caplog, value):
        """An invalid value falls back to 10 without raising, and the fallback
        is announced, so a typo'd value is not silently ignored.

        A TOML `drain_timeout = true` is not a one-second window: bool
        subclasses int, so plain float() coercion would turn `true` into 1.0
        and quietly shrink the grace period. Both bools are rejected.

        nan and inf survive float() but are not usable windows. Every
        comparison against nan is False, so a nan window slips past the
        positive check and reaches asyncio.wait, which then returns on the next
        loop step and force-cancels in-flight handlers with no grace. An inf
        window never ends, so shutdown would never finish.

        An int beyond float range is too large for float() and is invalid too.
        """
        with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
            engine = self._engine(drain_timeout=value)

        assert engine.drain_timeout == 10.0
        assert any(
            "drain_timeout_invalid_using_default" in r.message for r in caplog.records
        )

    @pytest.mark.parametrize("value", [0, -5])
    def test_non_positive_window_falls_back_to_ten_and_warns(self, caplog, value):
        """A zero window would give no grace at all, and a negative one is
        invalid, so both fall back to the default. The fallback is announced,
        so an operator is told the configured window was rejected rather than
        silently applied."""
        with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
            engine = self._engine(drain_timeout=value)

        assert engine.drain_timeout == 10.0
        assert any(
            "drain_timeout_not_positive_using_default" in r.message
            for r in caplog.records
        )

    def test_long_window_is_kept_without_a_kill_timeout_warning(self, caplog):
        """A window longer than 30 seconds is kept as configured and logs no
        warning: the Supervisor sizes its kill budget from it."""
        with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
            engine = self._engine(drain_timeout=45)

        assert engine.drain_timeout == 45.0
        assert [r.message for r in caplog.records if r.levelno >= logging.WARNING] == []


@pytest.mark.no_test_domain
class TestBrokerClose:
    """Test BaseBroker.close() default behavior."""

    def test_base_broker_close_is_noop(self):
        """Default close() on BaseBroker does nothing (no error)."""

        domain = Domain(name="Test")
        domain.init(traverse=False)

        broker = domain.brokers["default"]
        # Should not raise - inline broker inherits default no-op close()
        broker.close()


@pytest.mark.no_test_domain
class TestCacheClose:
    """Test BaseCache.close() default behavior."""

    def test_base_cache_close_is_noop(self):
        """Default close() on BaseCache does nothing (no error)."""

        domain = Domain(name="Test")
        domain.config["caches"] = {
            "default": {"provider": "memory"},
        }
        domain.init(traverse=False)

        cache = domain.caches["default"]
        # Should not raise - memory cache inherits default no-op close()
        cache.close()


@pytest.mark.no_test_domain
class TestBrokersReinitializeClosesExisting:
    """Test that Brokers._initialize() closes existing brokers first."""

    def test_reinitialize_closes_old_brokers(self):
        """Calling _initialize() again should close old broker connections."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        mock_broker = MagicMock()
        domain.brokers._brokers = {"default": mock_broker}

        # Re-initialize should close the old broker
        domain.brokers._initialize()

        mock_broker.close.assert_called_once()


@pytest.mark.no_test_domain
class TestCachesReinitializeClosesExisting:
    """Test that Caches._initialize() closes existing caches first."""

    def test_reinitialize_closes_old_caches(self):
        """Calling _initialize() again should close old cache connections."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        mock_cache = MagicMock()
        domain.caches._caches = {"default": mock_cache}

        # Re-initialize should close the old cache
        domain.caches._initialize()

        mock_cache.close.assert_called_once()


@pytest.mark.no_test_domain
class TestProvidersReinitializeClosesExisting:
    """Test that Providers._initialize() closes existing providers first."""

    def test_reinitialize_closes_old_providers(self):
        """Calling _initialize() again should close old provider connections."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        mock_provider = MagicMock()
        mock_provider.is_alive.return_value = True
        domain.providers._providers = {"default": mock_provider}

        # Re-initialize should close the old provider
        domain.providers._initialize()

        mock_provider.close.assert_called_once()


@pytest.mark.no_test_domain
class TestRegistryCloseErrorIsolation:
    """Test that registry close() methods continue on individual adapter errors."""

    @pytest.mark.parametrize(
        "registry, attribute, kind",
        [
            ("brokers", "_brokers", "broker"),
            ("caches", "_caches", "cache"),
            ("providers", "_providers", "provider"),
        ],
    )
    def test_close_continues_on_error(self, caplog, registry, attribute, kind):
        """close() calls close() on every adapter in the registry. If one
        adapter's close() raises, the other still gets closed."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        failing = MagicMock()
        failing.close.side_effect = RuntimeError("connection lost")
        ok = MagicMock()
        adapters = getattr(domain, registry)
        setattr(adapters, attribute, {"failing": failing, "ok": ok})

        with caplog.at_level(logging.ERROR):
            adapters.close()

        failing.close.assert_called_once()
        ok.close.assert_called_once()
        assert any(
            f"Error closing {kind} 'failing'" in r.message for r in caplog.records
        )


@pytest.mark.no_test_domain
class TestEventStoreCloseWhenNone:
    """Test EventStore.close() when no store is initialized."""

    def test_close_with_no_event_store(self):
        """close() is a no-op when _event_store is None."""
        domain = Domain(name="Test")
        # Don't call init — event store is None
        domain.event_store._event_store = None
        domain.event_store.close()  # Should not raise


@pytest.mark.no_test_domain
class TestEngineShutdownTaskExceptionRetrieval:
    """Test that Engine.shutdown() retrieves exceptions from done tasks."""

    def test_shutdown_retrieves_task_exceptions(self, caplog):
        """Completed tasks with exceptions are logged during shutdown."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            task_started = asyncio.Event()

            async def failing_task():
                task_started.set()
                # Small delay so the task is still "in-flight" when
                # shutdown collects asyncio.all_tasks(), but finishes
                # with an exception during the asyncio.wait() grace
                # period — landing in the `done` set.
                await asyncio.sleep(0.1)
                raise ValueError("task error")

            async def run_shutdown_with_failing_task():
                # Fire-and-forget on purpose: shutdown collects it via
                # asyncio.all_tasks(), and the loop keeps it alive meanwhile.
                asyncio.ensure_future(failing_task())  # noqa: RUF006
                await task_started.wait()
                await engine.shutdown()

            with caplog.at_level(logging.DEBUG):
                engine.loop.run_until_complete(run_shutdown_with_failing_task())

            assert any(
                "Task" in r.message and "raised during shutdown" in r.message
                for r in caplog.records
            )


@pytest.mark.no_test_domain
class TestRedisBrokerCloseEdgeCases:
    """Test RedisBroker.close() edge cases without needing Redis."""

    def test_close_when_already_none(self):
        """close() is a no-op when redis_instance is already None."""
        from protean.adapters.broker.redis import RedisBroker

        broker = object.__new__(RedisBroker)
        broker.redis_instance = None
        broker.name = "test"
        broker.close()  # Should not raise

    def test_close_exception_is_logged(self, caplog):
        """If redis_instance.close() raises, it's logged not re-raised."""
        from protean.adapters.broker.redis import RedisBroker

        broker = object.__new__(RedisBroker)
        broker.name = "test"
        mock_redis = MagicMock()
        mock_redis.close.side_effect = RuntimeError("connection error")
        broker.redis_instance = mock_redis

        with caplog.at_level(logging.ERROR):
            broker.close()  # Should not raise

        assert any("Error closing Redis broker" in r.message for r in caplog.records)


@pytest.mark.no_test_domain
class TestRedisBrokerReconnectAfterClose:
    """Reviving a closed Redis connection.

    Engine shutdown calls ``close()``, which sets ``redis_instance`` to ``None``.
    Under CI timing a straggler poll read or a test-teardown ``_data_reset`` can
    still run afterwards; these must reconnect transparently instead of raising
    ``AttributeError: 'NoneType' object has no attribute ...`` and killing the
    subscription poll loop. These tests use mocks and need no live Redis.
    """

    def _make_broker(self):
        from protean.adapters.broker.redis import RedisBroker

        broker = object.__new__(RedisBroker)
        broker.name = "test"
        broker.conn_info = {"URI": "redis://localhost:6379/0"}
        broker._pool_kwargs = {}
        broker.redis_instance = None
        broker._consumer_name = "consumer-test"
        broker._created_groups_set = set()
        broker._group_creation_times = {}
        return broker

    def test_client_reuses_live_instance_without_reconnecting(self):
        """The _client accessor does not reconnect when already connected."""
        broker = self._make_broker()
        broker.redis_instance = MagicMock()

        with patch("redis.Redis.from_url") as from_url:
            result = broker._client

        assert result is broker.redis_instance
        from_url.assert_not_called()

    def test_read_revives_closed_connection(self):
        """_read reconnects after close() instead of raising AttributeError."""
        broker = self._make_broker()
        # Pre-populate the group cache so _ensure_group does not hit Redis.
        broker._created_groups_set = {"stream:group"}
        mock_client = MagicMock()
        mock_client.xreadgroup.return_value = []

        with patch("redis.Redis.from_url", return_value=mock_client):
            result = broker._read("stream", "group", 1)

        assert result == []
        assert broker.redis_instance is mock_client
        assert mock_client.xreadgroup.called

    def test_data_reset_revives_closed_connection(self):
        """_data_reset reconnects after close() and flushes without raising."""
        broker = self._make_broker()
        broker._created_groups_set = {"stream:group"}
        broker._group_creation_times = {"group": 1.0}
        mock_client = MagicMock()

        with patch("redis.Redis.from_url", return_value=mock_client):
            broker._data_reset()

        mock_client.flushdb.assert_called_once()
        assert broker.redis_instance is mock_client
        assert broker._created_groups_set == set()
        assert broker._group_creation_times == {}

    def test_publish_revives_closed_connection(self):
        """_publish reconnects after close() instead of raising AttributeError."""
        broker = self._make_broker()
        mock_client = MagicMock()
        mock_client.xadd.return_value = b"1-0"

        with patch("redis.Redis.from_url", return_value=mock_client):
            identifier = broker._publish("stream", {"k": "v"})

        assert identifier == "1-0"
        assert broker.redis_instance is mock_client
        mock_client.xadd.assert_called_once()

    def test_read_blocking_reconnects_on_connection_error(self):
        """_read_blocking re-establishes the connection on a dropped socket.

        A "Connection closed by server" error on the blocking XREADGROUP is
        swallowed inside _read_blocking (returns []), so the base read_blocking
        wrapper's recovery never fires. _read_blocking must trigger the
        reconnect itself so the next poll tick reads from a healthy socket.
        """
        import redis

        broker = self._make_broker()
        broker._created_groups_set = {"stream:group"}
        mock_client = MagicMock()
        mock_client.xreadgroup.side_effect = redis.ConnectionError(
            "Connection closed by server."
        )
        mock_client.ping.return_value = True
        broker.redis_instance = mock_client

        result = broker._read_blocking(
            "stream", "group", "consumer", timeout_ms=100, count=1
        )

        assert result == []
        # The connection check pinged the client.
        mock_client.ping.assert_called_once()

    def test_read_blocking_does_not_reconnect_on_non_connection_error(self):
        """_read_blocking does not reconnect for unrelated errors (scope guard)."""
        broker = self._make_broker()
        broker._created_groups_set = {"stream:group"}
        mock_client = MagicMock()
        mock_client.xreadgroup.side_effect = ValueError("bad payload")
        broker.redis_instance = mock_client

        result = broker._read_blocking(
            "stream", "group", "consumer", timeout_ms=100, count=1
        )

        assert result == []
        # No connection check ran.
        mock_client.ping.assert_not_called()


@pytest.mark.no_test_domain
class TestRedisCacheCloseEdgeCases:
    """Test RedisCache.close() edge cases without needing Redis."""

    def test_close_when_already_none(self):
        """close() is a no-op when r is already None."""
        from protean.adapters.cache.redis import RedisCache

        cache = object.__new__(RedisCache)
        cache.r = None
        cache.name = "test"
        cache.close()  # Should not raise

    def test_close_exception_is_logged(self, caplog):
        """If r.close() raises, it's logged not re-raised."""
        from protean.adapters.cache.redis import RedisCache

        cache = object.__new__(RedisCache)
        cache.name = "test"
        mock_redis = MagicMock()
        mock_redis.close.side_effect = RuntimeError("connection error")
        cache.r = mock_redis

        with caplog.at_level(logging.ERROR):
            cache.close()  # Should not raise

        assert any("Error closing Redis cache" in r.message for r in caplog.records)
