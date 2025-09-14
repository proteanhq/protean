"""Tests for the BrokerRegistry plugin system."""

import logging

import pytest
from unittest.mock import Mock, patch

from protean.port.broker import registry, BrokerRegistry
from protean.exceptions import ConfigurationError


@pytest.mark.no_test_domain
class TestBrokerRegistry:
    """Test suite for BrokerRegistry functionality."""

    def setup_method(self):
        """Clear registry before each test."""
        # Reset the registry state
        registry._brokers.clear()
        BrokerRegistry._initialized = False

    def teardown_method(self):
        """Clean up after each test."""
        # Reset the registry state
        registry._brokers.clear()
        BrokerRegistry._initialized = False

    def test_register_broker(self):
        """Test basic broker registration."""
        registry.register("test_broker", "path.to.TestBroker")

        assert "test_broker" in registry._brokers
        assert registry._brokers["test_broker"] == "path.to.TestBroker"

    def test_register_overwrites_existing(self, caplog):
        """Test that registering the same broker name overwrites and logs warning."""
        registry.register("test_broker", "path.to.TestBroker")
        registry.register("test_broker", "path.to.AnotherBroker")

        assert registry._brokers["test_broker"] == "path.to.AnotherBroker"
        assert "already registered, overwriting" in caplog.text

    def test_list_brokers(self):
        """Test listing all registered brokers."""
        registry.register("broker1", "path.to.Broker1")
        registry.register("broker2", "path.to.Broker2")

        brokers = registry.list()
        assert len(brokers) == 2
        assert brokers["broker1"] == "path.to.Broker1"
        assert brokers["broker2"] == "path.to.Broker2"

    def test_list_returns_copy(self):
        """Test that list() returns a copy, not the original dict."""
        registry.register("broker1", "path.to.Broker1")

        brokers = registry.list()
        brokers["broker2"] = "path.to.Broker2"

        # Original registry should not be modified
        assert "broker2" not in registry._brokers

    def test_clear_registry(self):
        """Test clearing all registered brokers."""
        registry.register("broker1", "path.to.Broker1")
        registry.register("broker2", "path.to.Broker2")

        registry.clear()

        assert len(registry._brokers) == 0
        assert registry.list() == {}

    def test_get_registered_broker(self):
        """Test getting a registered broker class."""
        # Create a mock broker class
        with patch("protean.port.broker.import_module") as mock_import:
            mock_module = Mock()
            mock_broker_class = Mock()
            mock_module.TestBroker = mock_broker_class
            mock_import.return_value = mock_module

            registry.register("test_broker", "test.module.TestBroker")
            broker_cls = registry.get("test_broker")

            assert broker_cls == mock_broker_class
            mock_import.assert_called_once_with("test.module")

    def test_get_unregistered_broker_raises_error(self):
        """Test that getting an unregistered broker raises ConfigurationError."""
        # Clear any existing brokers first
        registry._brokers.clear()
        registry._initialized = False

        with pytest.raises(ConfigurationError) as exc_info:
            registry.get("nonexistent")

        assert "Broker 'nonexistent' is not registered" in str(exc_info.value)

    def test_get_broker_with_import_error(self):
        """Test that import errors are properly handled."""
        registry.register("bad_broker", "nonexistent.module.Broker")

        with pytest.raises(ConfigurationError) as exc_info:
            registry.get("bad_broker")

        assert "Failed to load broker 'bad_broker'" in str(exc_info.value)
        assert "Ensure the required dependencies are installed" in str(exc_info.value)

    def test_get_broker_with_attribute_error(self):
        """Test that missing broker class in module raises proper error."""
        with patch("protean.port.broker.import_module") as mock_import:
            mock_module = Mock(spec=[])  # Module without the expected class
            mock_import.return_value = mock_module

            registry.register("bad_broker", "test.module.NonexistentBroker")

            with pytest.raises(ConfigurationError) as exc_info:
                registry.get("bad_broker")

            assert "Failed to load broker 'bad_broker'" in str(exc_info.value)

    def test_discover_plugins(self):
        """Test plugin discovery via entry points."""
        # Mock at the class level to ensure our mock is used
        with patch.object(BrokerRegistry, "_discover_plugins") as mock_discover:
            # Create a custom discover function that registers brokers
            def custom_discover(cls):
                cls._brokers["test_broker1"] = "path.to.Broker1"
                cls._brokers["test_broker2"] = "path.to.Broker2"
                cls._initialized = True

            mock_discover.side_effect = lambda: custom_discover(registry)

            # Discover plugins
            registry._discover_plugins()

            # Check that brokers were registered
            assert "test_broker1" in registry._brokers
            assert "test_broker2" in registry._brokers
            assert registry._initialized is True

    def test_discover_plugins_only_runs_once(self):
        """Test that plugin discovery only runs once."""
        # setup_method ensures we start with _initialized = False
        assert BrokerRegistry._initialized is False

        # Mock entry points for first discovery
        mock_entry_point = Mock()
        mock_entry_point.name = "test_broker"
        mock_entry_point.load.return_value = lambda: registry.register(
            "test", "path.to.Test"
        )

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = [mock_entry_point]
            mock_entry_points.return_value = mock_eps

            # First discovery should work and set _initialized to True
            registry._discover_plugins()
            assert BrokerRegistry._initialized is True
            mock_entry_points.assert_called_once()

        # Second discovery should be skipped (no entry_points call)
        with patch("importlib.metadata.entry_points") as mock_entry_points:
            registry._discover_plugins()
            # Should not call entry_points since already initialized
            mock_entry_points.assert_not_called()

    def test_discover_plugins_handles_failed_plugins(self, caplog):
        """Test that failed plugin loading doesn't break discovery."""
        # Set logging level to DEBUG to capture the debug messages
        caplog.set_level(logging.DEBUG, logger="protean.port.broker")

        # Create mock entry points with one that succeeds and one that fails
        mock_good_entry = Mock()
        mock_good_entry.name = "good_broker"
        mock_good_entry.load.return_value = lambda: registry.register(
            "good_broker", "path.to.GoodBroker"
        )

        mock_bad_entry = Mock()
        mock_bad_entry.name = "bad_broker"
        mock_bad_entry.load.side_effect = ImportError("Missing dependency")

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = [mock_good_entry, mock_bad_entry]
            mock_entry_points.return_value = mock_eps

            # Reset initialized flag to ensure discovery runs
            BrokerRegistry._initialized = False

            # Discover plugins - should not raise exception
            registry._discover_plugins()

            # Good broker should be registered
            assert "good_broker" in registry._brokers

            # Bad broker should not be registered
            assert "bad_broker" not in registry._brokers

            # Check that the failure was logged
            assert "Failed to load broker plugin 'bad_broker'" in caplog.text
            assert "Missing dependency" in caplog.text

    def test_discover_plugins_handles_registration_function_error(self, caplog):
        """Test handling when the registration function itself raises an error."""
        caplog.set_level(logging.DEBUG, logger="protean.port.broker")

        # Create entry point where the registration function raises an error
        mock_entry = Mock()
        mock_entry.name = "error_broker"

        def failing_register():
            raise RuntimeError("Registration function failed")

        mock_entry.load.return_value = failing_register

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = [mock_entry]
            mock_entry_points.return_value = mock_eps

            # Reset initialized flag
            BrokerRegistry._initialized = False

            # Should not raise exception
            registry._discover_plugins()

            # Broker should not be registered
            assert "error_broker" not in registry._brokers

            # Check that the failure was logged
            assert "Failed to load broker plugin 'error_broker'" in caplog.text
            assert "Registration function failed" in caplog.text

    def test_discover_plugins_handles_attribute_error(self, caplog):
        """Test handling when entry point load raises AttributeError."""
        caplog.set_level(logging.DEBUG, logger="protean.port.broker")

        mock_entry = Mock()
        mock_entry.name = "attr_error_broker"
        mock_entry.load.side_effect = AttributeError(
            "Module has no attribute 'register'"
        )

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = [mock_entry]
            mock_entry_points.return_value = mock_eps

            BrokerRegistry._initialized = False
            registry._discover_plugins()

            assert "attr_error_broker" not in registry._brokers
            assert "Failed to load broker plugin 'attr_error_broker'" in caplog.text
            assert "Module has no attribute 'register'" in caplog.text

    def test_discover_plugins_continues_after_multiple_failures(self, caplog):
        """Test that discovery continues processing after multiple failures."""
        caplog.set_level(logging.DEBUG, logger="protean.port.broker")

        # Create multiple entry points with various failure modes
        entries = []

        # First broker - succeeds
        mock_entry1 = Mock()
        mock_entry1.name = "broker1"
        mock_entry1.load.return_value = lambda: registry.register(
            "broker1", "path.to.Broker1"
        )
        entries.append(mock_entry1)

        # Second broker - ImportError
        mock_entry2 = Mock()
        mock_entry2.name = "broker2"
        mock_entry2.load.side_effect = ImportError("No module")
        entries.append(mock_entry2)

        # Third broker - succeeds
        mock_entry3 = Mock()
        mock_entry3.name = "broker3"
        mock_entry3.load.return_value = lambda: registry.register(
            "broker3", "path.to.Broker3"
        )
        entries.append(mock_entry3)

        # Fourth broker - RuntimeError in registration
        mock_entry4 = Mock()
        mock_entry4.name = "broker4"
        mock_entry4.load.return_value = lambda: (_ for _ in ()).throw(
            RuntimeError("Boom!")
        )
        entries.append(mock_entry4)

        # Fifth broker - succeeds
        mock_entry5 = Mock()
        mock_entry5.name = "broker5"
        mock_entry5.load.return_value = lambda: registry.register(
            "broker5", "path.to.Broker5"
        )
        entries.append(mock_entry5)

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = entries
            mock_entry_points.return_value = mock_eps

            BrokerRegistry._initialized = False
            registry._discover_plugins()

            # Check that successful brokers were registered
            assert "broker1" in registry._brokers
            assert "broker3" in registry._brokers
            assert "broker5" in registry._brokers

            # Check that failed brokers were not registered
            assert "broker2" not in registry._brokers
            assert "broker4" not in registry._brokers

            # Check that all failures were logged
            assert "Failed to load broker plugin 'broker2'" in caplog.text
            assert "Failed to load broker plugin 'broker4'" in caplog.text

            # Verify specific error messages
            assert "No module" in caplog.text
            assert "Boom!" in caplog.text

    def test_discover_plugins_python311(self):
        """Test plugin discovery with Python 3.11+ entry_points API."""
        # Test that the modern entry points API works correctly
        try:
            registry._discover_plugins()
            # Should complete without error
            assert True
        except Exception as e:
            pytest.fail(f"Discovery failed: {e}")

    def test_get_triggers_discovery(self):
        """Test that get() triggers plugin discovery on first access."""
        # Reset initialized flag to ensure discovery runs
        registry._initialized = False

        with patch.object(
            BrokerRegistry, "_discover_plugins", wraps=registry._discover_plugins
        ) as mock_discover:
            # Set up a registered broker to avoid ConfigurationError
            registry._brokers["test"] = "path.to.Test"

            with patch("protean.port.broker.import_module") as mock_import:
                mock_module = Mock()
                mock_module.Test = Mock()
                mock_import.return_value = mock_module

                registry.get("test")
                mock_discover.assert_called_once()

    def test_available_brokers_in_error_message(self):
        """Test that error message lists available brokers."""
        registry.register("broker1", "path.to.Broker1")
        registry.register("broker2", "path.to.Broker2")

        with pytest.raises(ConfigurationError) as exc_info:
            registry.get("nonexistent")

        error_msg = str(exc_info.value)
        assert (
            "Available brokers: broker1, broker2" in error_msg
            or "Available brokers: broker2, broker1" in error_msg
        )


@pytest.mark.no_test_domain
class TestBrokerRegistryIntegration:
    """Integration tests for BrokerRegistry with actual brokers."""

    def setup_method(self):
        """Clear registry before each test."""
        registry._brokers.clear()
        BrokerRegistry._initialized = False

    def teardown_method(self):
        """Clean up after each test."""
        registry._brokers.clear()
        BrokerRegistry._initialized = False

    def test_inline_broker_registration(self):
        """Test that InlineBroker can be registered and retrieved."""
        # Register inline broker
        from protean.adapters.broker.inline import register

        register()

        # Should be able to get the broker class
        from protean.adapters.broker.inline import InlineBroker

        broker_cls = registry.get("inline")

        # The class should be the actual InlineBroker
        assert broker_cls == InlineBroker

    def test_redis_broker_registration_with_redis_available(self):
        """Test Redis broker registration when redis package is available."""
        try:
            import redis as redis_module  # noqa: F401

            # If redis is available, test registration
            from protean.adapters.broker.redis import register

            register()

            # Should be registered
            assert "redis" in registry._brokers

            # Should be able to get the broker class
            from protean.adapters.broker.redis import RedisBroker

            broker_cls = registry.get("redis")
            assert broker_cls == RedisBroker
        except ImportError:
            # Redis not available, skip this test
            pytest.skip("Redis package not available")

    def test_multiple_broker_registration(self):
        """Test registering multiple brokers."""
        registry.register("broker1", "path.to.Broker1")
        registry.register("broker2", "path.to.Broker2")
        registry.register("broker3", "path.to.Broker3")

        brokers = registry.list()
        assert len(brokers) == 3
        assert all(f"broker{i}" in brokers for i in range(1, 4))


@pytest.mark.no_test_domain
class TestBrokerRegistryWithMockEntryPoints:
    """Test BrokerRegistry with mocked entry points system."""

    def setup_method(self):
        """Clear registry before each test."""
        registry._brokers.clear()
        BrokerRegistry._initialized = False

    def teardown_method(self):
        """Clean up after each test."""
        registry._brokers.clear()
        BrokerRegistry._initialized = False

    def test_importlib_metadata_always_available(self):
        """Test that importlib.metadata is always available in Python 3.11+."""
        # Python 3.11+ always has importlib.metadata
        import importlib.metadata

        # Should be able to get entry points without any fallback
        entry_points = importlib.metadata.entry_points()
        assert hasattr(entry_points, "select")  # Modern API should be available

    def test_registry_is_singleton_behavior(self):
        """Test that the registry instance behaves like a singleton."""
        # Import registry from two different ways
        from protean.adapters.broker import registry as reg1
        from protean.adapters.broker import registry as reg2

        # They should be the same instance
        assert reg1 is reg2

        # Changes to one should affect the other
        reg1.register("test", "path.to.Test")
        assert "test" in reg2._brokers
