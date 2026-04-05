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

            assert any(
                "Error during domain infrastructure cleanup" in r.message
                for r in caplog.records
            )


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
