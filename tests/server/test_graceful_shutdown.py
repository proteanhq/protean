"""Tests for graceful resource cleanup on Engine shutdown (#792)."""

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from protean import Domain
from protean.server.engine import Engine


@pytest.mark.no_test_domain
class TestDomainClose:
    """Test Domain.close() shuts down all infrastructure adapters."""

    def test_close_calls_provider_close(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with patch.object(domain.providers, "close") as mock_close:
            domain.close()
            mock_close.assert_called_once()

    def test_close_calls_broker_close(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with patch.object(domain.brokers, "close") as mock_close:
            domain.close()
            mock_close.assert_called_once()

    def test_close_calls_cache_close(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with patch.object(domain.caches, "close") as mock_close:
            domain.close()
            mock_close.assert_called_once()

    def test_close_calls_event_store_close(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with patch.object(domain.event_store, "close") as mock_close:
            domain.close()
            mock_close.assert_called_once()

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
        """Event store closed first, providers closed last."""
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

    def test_shutdown_calls_domain_close(self):
        """Engine.shutdown() should call domain.close() after subscriptions stop."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            with patch.object(domain, "close") as mock_close:
                engine.loop.run_until_complete(engine.shutdown())
                mock_close.assert_called_once()

    def test_shutdown_closes_domain_after_subscriptions(self):
        """domain.close() is called after subscription shutdown completes."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            call_order = []

            # Mock a subscription
            mock_subscription = MagicMock()

            async def mock_shutdown():
                call_order.append("subscription_shutdown")

            mock_subscription.shutdown = mock_shutdown
            engine._subscriptions = {"test": mock_subscription}

            original_close = domain.close

            def tracked_close():
                call_order.append("domain_close")
                original_close()

            with patch.object(domain, "close", side_effect=tracked_close):
                engine.loop.run_until_complete(engine.shutdown())

            assert "subscription_shutdown" in call_order
            assert "domain_close" in call_order
            assert call_order.index("subscription_shutdown") < call_order.index(
                "domain_close"
            )

    def test_shutdown_domain_close_error_does_not_prevent_loop_stop(self, caplog):
        """Even if domain.close() raises, the loop should still stop."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            with patch.object(
                domain, "close", side_effect=RuntimeError("cleanup failed")
            ):
                with caplog.at_level(logging.ERROR):
                    engine.loop.run_until_complete(engine.shutdown())

            assert any("engine.cleanup_failed" in r.message for r in caplog.records)


@pytest.mark.no_test_domain
class TestInFlightTaskCompletion:
    """Test that in-flight message handlers complete before forced cancellation."""

    def test_inflight_tasks_get_grace_period(self):
        """Tasks running when shutdown begins get a grace period to finish."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            task_completed = False

            async def slow_handler():
                nonlocal task_completed
                await asyncio.sleep(0.1)  # Short delay, well within timeout
                task_completed = True

            # Create a task that simulates an in-flight handler
            engine.loop.run_until_complete(self._run_with_task(engine, slow_handler))

            assert task_completed

    async def _run_with_task(self, engine, handler_coro):
        """Helper to run shutdown with an in-flight task."""
        task = asyncio.ensure_future(handler_coro())
        await engine.shutdown()
        return task


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
class TestBrokersRegistryClose:
    """Test that the Brokers registry class close() iterates all brokers."""

    def test_brokers_registry_close_calls_all(self):
        """Brokers.close() calls close() on every registered broker."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        mock_broker_1 = MagicMock()
        mock_broker_2 = MagicMock()
        domain.brokers._brokers = {"default": mock_broker_1, "secondary": mock_broker_2}

        domain.brokers.close()

        mock_broker_1.close.assert_called_once()
        mock_broker_2.close.assert_called_once()


@pytest.mark.no_test_domain
class TestCachesRegistryClose:
    """Test that the Caches registry class close() iterates all caches."""

    def test_caches_registry_close_calls_all(self):
        """Caches.close() calls close() on every registered cache."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        mock_cache_1 = MagicMock()
        mock_cache_2 = MagicMock()
        domain.caches._caches = {"default": mock_cache_1, "secondary": mock_cache_2}

        domain.caches.close()

        mock_cache_1.close.assert_called_once()
        mock_cache_2.close.assert_called_once()


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

    def test_brokers_close_continues_on_error(self, caplog):
        """If one broker's close() raises, the other still gets closed."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        failing_broker = MagicMock()
        failing_broker.close.side_effect = RuntimeError("connection lost")
        ok_broker = MagicMock()
        domain.brokers._brokers = {"failing": failing_broker, "ok": ok_broker}

        with caplog.at_level(logging.ERROR):
            domain.brokers.close()

        ok_broker.close.assert_called_once()
        assert any(
            "Error closing broker 'failing'" in r.message for r in caplog.records
        )

    def test_caches_close_continues_on_error(self, caplog):
        """If one cache's close() raises, the other still gets closed."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        failing_cache = MagicMock()
        failing_cache.close.side_effect = RuntimeError("connection lost")
        ok_cache = MagicMock()
        domain.caches._caches = {"failing": failing_cache, "ok": ok_cache}

        with caplog.at_level(logging.ERROR):
            domain.caches.close()

        ok_cache.close.assert_called_once()
        assert any("Error closing cache 'failing'" in r.message for r in caplog.records)

    def test_providers_close_continues_on_error(self, caplog):
        """If one provider's close() raises, the other still gets closed."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        failing_provider = MagicMock()
        failing_provider.close.side_effect = RuntimeError("connection lost")
        ok_provider = MagicMock()
        domain.providers._providers = {
            "failing": failing_provider,
            "ok": ok_provider,
        }

        with caplog.at_level(logging.ERROR):
            domain.providers.close()

        ok_provider.close.assert_called_once()
        assert any(
            "Error closing provider 'failing'" in r.message for r in caplog.records
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
                asyncio.ensure_future(failing_task())
                await task_started.wait()
                await engine.shutdown()

            with caplog.at_level(logging.DEBUG):
                engine.loop.run_until_complete(run_shutdown_with_failing_task())

            assert any(
                "Task" in r.message and "raised during shutdown" in r.message
                for r in caplog.records
            )

    def test_shutdown_cancels_tasks_exceeding_timeout(self, caplog):
        """Tasks that don't finish within the grace period are cancelled."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            async def stuck_task():
                await asyncio.sleep(3600)  # Will never finish on its own

            async def run_shutdown_with_stuck_task():
                task = asyncio.ensure_future(stuck_task())
                await engine.shutdown()
                assert task.cancelled()

            with caplog.at_level(logging.DEBUG):
                # Patch wait to use a very short timeout
                original_wait = asyncio.wait

                async def short_wait(tasks, **kwargs):
                    return await original_wait(tasks, timeout=0.1)

                with patch(
                    "protean.server.engine.asyncio.wait", side_effect=short_wait
                ):
                    engine.loop.run_until_complete(run_shutdown_with_stuck_task())

            assert any("engine.cancelling_tasks" in r.message for r in caplog.records)


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
    """Reviving a closed Redis connection (#1055).

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

    def test_client_revives_when_instance_is_none(self):
        """The _client accessor reconnects when redis_instance is None."""
        broker = self._make_broker()
        mock_client = MagicMock()

        with patch("redis.Redis.from_url", return_value=mock_client) as from_url:
            result = broker._client

        assert result is mock_client
        assert broker.redis_instance is mock_client
        from_url.assert_called_once()

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

        mock_client.flushall.assert_called_once()
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
        broker.redis_instance = mock_client

        with patch.object(
            broker, "_ensure_connection", return_value=True
        ) as ensure_connection:
            result = broker._read_blocking(
                "stream", "group", "consumer", timeout_ms=100, count=1
            )

        assert result == []
        ensure_connection.assert_called_once()

    def test_read_blocking_does_not_reconnect_on_non_connection_error(self):
        """_read_blocking does not reconnect for unrelated errors (scope guard)."""
        broker = self._make_broker()
        broker._created_groups_set = {"stream:group"}
        mock_client = MagicMock()
        mock_client.xreadgroup.side_effect = ValueError("bad payload")
        broker.redis_instance = mock_client

        with patch.object(broker, "_ensure_connection") as ensure_connection:
            result = broker._read_blocking(
                "stream", "group", "consumer", timeout_ms=100, count=1
            )

        assert result == []
        ensure_connection.assert_not_called()


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
