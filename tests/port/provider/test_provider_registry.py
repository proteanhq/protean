"""Tests for the ProviderRegistry plugin system."""

import logging

import pytest
from unittest.mock import Mock, patch

from protean.port.provider import registry, ProviderRegistry
from protean.exceptions import ConfigurationError


@pytest.mark.no_test_domain
class TestProviderRegistry:
    """Test suite for ProviderRegistry functionality."""

    def setup_method(self):
        """Clear registry and prevent real entry-point discovery."""
        self._saved_providers = registry._providers.copy()
        self._saved_initialized = ProviderRegistry._initialized
        registry._providers.clear()
        ProviderRegistry._initialized = True  # Prevent real discovery

    def teardown_method(self):
        """Restore registry state."""
        registry._providers.clear()
        registry._providers.update(self._saved_providers)
        ProviderRegistry._initialized = self._saved_initialized

    def test_register_provider(self):
        """Test basic provider registration."""
        registry.register("test_provider", "path.to.TestProvider")

        assert "test_provider" in registry._providers
        assert registry._providers["test_provider"] == "path.to.TestProvider"

    def test_register_overwrites_existing(self, caplog):
        """Test that registering the same provider name overwrites and logs warning."""
        registry.register("test_provider", "path.to.TestProvider")
        registry.register("test_provider", "path.to.AnotherProvider")

        assert registry._providers["test_provider"] == "path.to.AnotherProvider"
        assert "already registered, overwriting" in caplog.text

    def test_list_providers(self):
        """Test listing all registered providers."""
        registry.register("provider1", "path.to.Provider1")
        registry.register("provider2", "path.to.Provider2")

        providers = registry.list()
        assert len(providers) == 2
        assert providers["provider1"] == "path.to.Provider1"
        assert providers["provider2"] == "path.to.Provider2"

    def test_list_returns_copy(self):
        """Test that list() returns a copy, not the original dict."""
        registry.register("provider1", "path.to.Provider1")

        providers = registry.list()
        providers["provider2"] = "path.to.Provider2"

        # Original registry should not be modified
        assert "provider2" not in registry._providers

    def test_list_does_not_trigger_discovery(self):
        """Test that list() does not trigger plugin discovery (matches broker pattern)."""
        ProviderRegistry._initialized = False

        with patch.object(ProviderRegistry, "_discover_plugins") as mock_discover:
            registry.list()
            mock_discover.assert_not_called()

    def test_clear_registry(self):
        """Test clearing all registered providers."""
        registry.register("provider1", "path.to.Provider1")
        registry.register("provider2", "path.to.Provider2")

        registry.clear()

        assert len(registry._providers) == 0
        assert registry.list() == {}

    def test_get_registered_provider(self):
        """Test getting a registered provider class."""
        with patch("protean.port.provider.import_module") as mock_import:
            mock_module = Mock()
            mock_provider_class = Mock()
            mock_provider_class.validate_lookups = Mock(return_value=[])
            mock_module.TestProvider = mock_provider_class
            mock_import.return_value = mock_module

            registry.register("test_provider", "test.module.TestProvider")
            provider_cls = registry.get("test_provider")

            assert provider_cls == mock_provider_class
            mock_import.assert_called_once_with("test.module")

    def test_get_warns_on_missing_required_lookups(self, caplog):
        """Test that get() logs a warning when provider is missing required lookups."""
        caplog.set_level(logging.WARNING, logger="protean.port.provider")

        with patch("protean.port.provider.import_module") as mock_import:
            mock_module = Mock()
            mock_provider_class = Mock()
            mock_provider_class.__name__ = "IncompleteProvider"
            mock_provider_class.validate_lookups = Mock(
                return_value=["contains", "icontains"]
            )
            mock_module.IncompleteProvider = mock_provider_class
            mock_import.return_value = mock_module

            registry.register("incomplete", "test.module.IncompleteProvider")
            provider_cls = registry.get("incomplete")

            assert provider_cls == mock_provider_class
            assert "missing required lookups" in caplog.text
            assert "contains" in caplog.text
            assert "icontains" in caplog.text

    def test_get_no_warning_when_all_lookups_present(self, caplog):
        """Test that get() does not warn when all required lookups are registered."""
        caplog.set_level(logging.WARNING, logger="protean.port.provider")

        with patch("protean.port.provider.import_module") as mock_import:
            mock_module = Mock()
            mock_provider_class = Mock()
            mock_provider_class.__name__ = "CompleteProvider"
            mock_provider_class.validate_lookups = Mock(return_value=[])
            mock_module.CompleteProvider = mock_provider_class
            mock_import.return_value = mock_module

            registry.register("complete", "test.module.CompleteProvider")
            registry.get("complete")

            assert "missing required lookups" not in caplog.text

    def test_get_unregistered_provider_raises_error(self):
        """Test that getting an unregistered provider raises ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            registry.get("nonexistent")

        assert "Unknown database provider 'nonexistent'" in str(exc_info.value)

    def test_get_none_provider_raises_error(self):
        """Test that getting None provider raises ConfigurationError with useful message."""
        with pytest.raises(ConfigurationError) as exc_info:
            registry.get(None)

        assert "Unknown database provider 'None'" in str(exc_info.value)

    def test_get_provider_with_import_error(self):
        """Test that import errors are properly handled."""
        registry.register("bad_provider", "nonexistent.module.Provider")

        with pytest.raises(ConfigurationError) as exc_info:
            registry.get("bad_provider")

        assert "Failed to load provider 'bad_provider'" in str(exc_info.value)
        assert "Ensure the required dependencies are installed" in str(exc_info.value)

    def test_get_provider_with_attribute_error(self):
        """Test that missing provider class in module raises proper error."""
        with patch("protean.port.provider.import_module") as mock_import:
            mock_module = Mock(spec=[])  # Module without the expected class
            mock_import.return_value = mock_module

            registry.register("bad_provider", "test.module.NonexistentProvider")

            with pytest.raises(ConfigurationError) as exc_info:
                registry.get("bad_provider")

            assert "Failed to load provider 'bad_provider'" in str(exc_info.value)

    def test_available_providers_in_error_message(self):
        """Test that error message lists available providers."""
        registry.register("memory", "path.to.MemoryProvider")
        registry.register("postgresql", "path.to.PostgresqlProvider")

        with pytest.raises(ConfigurationError) as exc_info:
            registry.get("nonexistent")

        error_msg = str(exc_info.value)
        assert "Available providers:" in error_msg
        assert "memory" in error_msg
        assert "postgresql" in error_msg

    def test_available_providers_sorted_in_error_message(self):
        """Test that available providers are sorted alphabetically in error message."""
        ProviderRegistry._initialized = True  # Prevent real discovery
        registry.register("sqlite", "path.to.SqliteProvider")
        registry.register("memory", "path.to.MemoryProvider")
        registry.register("postgresql", "path.to.PostgresqlProvider")

        with pytest.raises(ConfigurationError) as exc_info:
            registry.get("nonexistent")

        error_msg = str(exc_info.value)
        assert "memory, postgresql, sqlite" in error_msg

    def test_no_available_providers_in_error_message(self):
        """Test error message when no providers are registered."""
        registry._providers.clear()
        ProviderRegistry._initialized = True  # Prevent real discovery

        with pytest.raises(ConfigurationError) as exc_info:
            registry.get("nonexistent")

        assert "Available providers: none" in str(exc_info.value)


@pytest.mark.no_test_domain
class TestProviderRegistryDiscovery:
    """Test plugin discovery via entry points."""

    def setup_method(self):
        """Save and clear registry before each test."""
        self._saved_providers = registry._providers.copy()
        self._saved_initialized = ProviderRegistry._initialized
        registry._providers.clear()
        ProviderRegistry._initialized = False

    def teardown_method(self):
        """Restore registry state."""
        registry._providers.clear()
        registry._providers.update(self._saved_providers)
        ProviderRegistry._initialized = self._saved_initialized

    def test_discover_plugins(self):
        """Test plugin discovery via entry points."""
        with patch.object(ProviderRegistry, "_discover_plugins") as mock_discover:

            def custom_discover(cls):
                cls._providers["test_provider1"] = "path.to.Provider1"
                cls._providers["test_provider2"] = "path.to.Provider2"
                cls._initialized = True

            mock_discover.side_effect = lambda: custom_discover(registry)

            registry._discover_plugins()

            assert "test_provider1" in registry._providers
            assert "test_provider2" in registry._providers
            assert registry._initialized is True

    def test_discover_plugins_only_runs_once(self):
        """Test that plugin discovery only runs once."""
        assert ProviderRegistry._initialized is False

        mock_entry_point = Mock()
        mock_entry_point.name = "test_provider"
        mock_entry_point.load.return_value = lambda: registry.register(
            "test", "path.to.Test"
        )

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = [mock_entry_point]
            mock_entry_points.return_value = mock_eps

            # First discovery should work and set _initialized to True
            registry._discover_plugins()
            assert ProviderRegistry._initialized is True
            mock_entry_points.assert_called_once()

        # Second discovery should be skipped (no entry_points call)
        with patch("importlib.metadata.entry_points") as mock_entry_points:
            registry._discover_plugins()
            mock_entry_points.assert_not_called()

    def test_discover_plugins_handles_failed_plugins(self, caplog):
        """Test that failed plugin loading doesn't break discovery."""
        caplog.set_level(logging.DEBUG, logger="protean.port.provider")

        mock_good_entry = Mock()
        mock_good_entry.name = "good_provider"
        mock_good_entry.load.return_value = lambda: registry.register(
            "good_provider", "path.to.GoodProvider"
        )

        mock_bad_entry = Mock()
        mock_bad_entry.name = "bad_provider"
        mock_bad_entry.load.side_effect = ImportError("Missing dependency")

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = [mock_good_entry, mock_bad_entry]
            mock_entry_points.return_value = mock_eps

            ProviderRegistry._initialized = False
            registry._discover_plugins()

            assert "good_provider" in registry._providers
            assert "bad_provider" not in registry._providers
            assert "Failed to load provider plugin 'bad_provider'" in caplog.text
            assert "Missing dependency" in caplog.text

    def test_discover_plugins_handles_registration_function_error(self, caplog):
        """Test handling when the registration function itself raises an error."""
        caplog.set_level(logging.DEBUG, logger="protean.port.provider")

        mock_entry = Mock()
        mock_entry.name = "error_provider"

        def failing_register():
            raise RuntimeError("Registration function failed")

        mock_entry.load.return_value = failing_register

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = [mock_entry]
            mock_entry_points.return_value = mock_eps

            ProviderRegistry._initialized = False
            registry._discover_plugins()

            assert "error_provider" not in registry._providers
            assert "Failed to load provider plugin 'error_provider'" in caplog.text
            assert "Registration function failed" in caplog.text

    def test_discover_plugins_handles_attribute_error(self, caplog):
        """Test handling when entry point load raises AttributeError."""
        caplog.set_level(logging.DEBUG, logger="protean.port.provider")

        mock_entry = Mock()
        mock_entry.name = "attr_error_provider"
        mock_entry.load.side_effect = AttributeError(
            "Module has no attribute 'register'"
        )

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = [mock_entry]
            mock_entry_points.return_value = mock_eps

            ProviderRegistry._initialized = False
            registry._discover_plugins()

            assert "attr_error_provider" not in registry._providers
            assert "Failed to load provider plugin 'attr_error_provider'" in caplog.text
            assert "Module has no attribute 'register'" in caplog.text

    def test_discover_plugins_continues_after_multiple_failures(self, caplog):
        """Test that discovery continues processing after multiple failures."""
        caplog.set_level(logging.DEBUG, logger="protean.port.provider")

        entries = []

        # First provider - succeeds
        mock_entry1 = Mock()
        mock_entry1.name = "provider1"
        mock_entry1.load.return_value = lambda: registry.register(
            "provider1", "path.to.Provider1"
        )
        entries.append(mock_entry1)

        # Second provider - ImportError
        mock_entry2 = Mock()
        mock_entry2.name = "provider2"
        mock_entry2.load.side_effect = ImportError("No module")
        entries.append(mock_entry2)

        # Third provider - succeeds
        mock_entry3 = Mock()
        mock_entry3.name = "provider3"
        mock_entry3.load.return_value = lambda: registry.register(
            "provider3", "path.to.Provider3"
        )
        entries.append(mock_entry3)

        # Fourth provider - RuntimeError in registration
        mock_entry4 = Mock()
        mock_entry4.name = "provider4"
        mock_entry4.load.return_value = lambda: (_ for _ in ()).throw(
            RuntimeError("Boom!")
        )
        entries.append(mock_entry4)

        # Fifth provider - succeeds
        mock_entry5 = Mock()
        mock_entry5.name = "provider5"
        mock_entry5.load.return_value = lambda: registry.register(
            "provider5", "path.to.Provider5"
        )
        entries.append(mock_entry5)

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = entries
            mock_entry_points.return_value = mock_eps

            ProviderRegistry._initialized = False
            registry._discover_plugins()

            assert "provider1" in registry._providers
            assert "provider3" in registry._providers
            assert "provider5" in registry._providers
            assert "provider2" not in registry._providers
            assert "provider4" not in registry._providers

            assert "Failed to load provider plugin 'provider2'" in caplog.text
            assert "Failed to load provider plugin 'provider4'" in caplog.text
            assert "No module" in caplog.text
            assert "Boom!" in caplog.text

    def test_get_triggers_discovery(self):
        """Test that get() triggers plugin discovery on first access."""
        registry._initialized = False

        with patch.object(
            ProviderRegistry, "_discover_plugins", wraps=registry._discover_plugins
        ) as mock_discover:
            registry._providers["test"] = "path.to.Test"

            with patch("protean.port.provider.import_module") as mock_import:
                mock_module = Mock()
                mock_provider_class = Mock()
                mock_provider_class.validate_lookups = Mock(return_value=[])
                mock_module.Test = mock_provider_class
                mock_import.return_value = mock_module

                registry.get("test")
                mock_discover.assert_called_once()

    def test_discover_plugins_python311(self):
        """Test plugin discovery with Python 3.11+ entry_points API."""
        try:
            registry._discover_plugins()
            assert True
        except Exception as e:
            pytest.fail(f"Discovery failed: {e}")


@pytest.mark.no_test_domain
class TestProviderRegistryIntegration:
    """Integration tests for ProviderRegistry with actual providers."""

    def setup_method(self):
        """Save and clear registry before each test."""
        self._saved_providers = registry._providers.copy()
        self._saved_initialized = ProviderRegistry._initialized
        registry._providers.clear()
        ProviderRegistry._initialized = True  # Prevent real discovery

    def teardown_method(self):
        """Restore registry state."""
        registry._providers.clear()
        registry._providers.update(self._saved_providers)
        ProviderRegistry._initialized = self._saved_initialized

    def test_memory_provider_registration(self):
        """Test that MemoryProvider can be registered and retrieved."""
        from protean.adapters.repository.memory import register

        register()

        from protean.adapters.repository.memory import MemoryProvider

        provider_cls = registry.get("memory")
        assert provider_cls == MemoryProvider

    def test_postgresql_provider_registration(self):
        """Test PostgreSQL provider registration when sqlalchemy is available."""
        pytest.importorskip("sqlalchemy", reason="SQLAlchemy package not available")

        from protean.adapters.repository.sqlalchemy import register_postgresql

        register_postgresql()

        assert "postgresql" in registry._providers

        from protean.adapters.repository.sqlalchemy import PostgresqlProvider

        provider_cls = registry.get("postgresql")
        assert provider_cls == PostgresqlProvider

    def test_sqlite_provider_registration(self):
        """Test SQLite provider registration when sqlalchemy is available."""
        pytest.importorskip("sqlalchemy", reason="SQLAlchemy package not available")

        from protean.adapters.repository.sqlalchemy import register_sqlite

        register_sqlite()

        assert "sqlite" in registry._providers

        from protean.adapters.repository.sqlalchemy import SqliteProvider

        provider_cls = registry.get("sqlite")
        assert provider_cls == SqliteProvider

    def test_mssql_provider_registration(self):
        """Test MSSQL provider registration when sqlalchemy is available."""
        pytest.importorskip("sqlalchemy", reason="SQLAlchemy package not available")

        from protean.adapters.repository.sqlalchemy import register_mssql

        register_mssql()

        assert "mssql" in registry._providers

        from protean.adapters.repository.sqlalchemy import MssqlProvider

        provider_cls = registry.get("mssql")
        assert provider_cls == MssqlProvider

    def test_elasticsearch_provider_registration(self):
        """Test Elasticsearch provider registration when elasticsearch is available."""
        pytest.importorskip(
            "elasticsearch", reason="Elasticsearch package not available"
        )

        from protean.adapters.repository.elasticsearch import register

        register()

        assert "elasticsearch" in registry._providers

        from protean.adapters.repository.elasticsearch import ESProvider

        provider_cls = registry.get("elasticsearch")
        assert provider_cls == ESProvider

    def test_multiple_provider_registration(self):
        """Test registering multiple providers."""
        registry.register("provider1", "path.to.Provider1")
        registry.register("provider2", "path.to.Provider2")
        registry.register("provider3", "path.to.Provider3")

        providers = registry.list()
        assert len(providers) == 3
        assert all(f"provider{i}" in providers for i in range(1, 4))


@pytest.mark.no_test_domain
class TestProviderRegistryWithMockEntryPoints:
    """Test ProviderRegistry with mocked entry points system."""

    def setup_method(self):
        """Save and clear registry before each test."""
        self._saved_providers = registry._providers.copy()
        self._saved_initialized = ProviderRegistry._initialized
        registry._providers.clear()
        ProviderRegistry._initialized = True  # Prevent real discovery

    def teardown_method(self):
        """Restore registry state."""
        registry._providers.clear()
        registry._providers.update(self._saved_providers)
        ProviderRegistry._initialized = self._saved_initialized

    def test_importlib_metadata_always_available(self):
        """Test that importlib.metadata is always available in Python 3.11+."""
        import importlib.metadata

        entry_points = importlib.metadata.entry_points()
        assert hasattr(entry_points, "select")

    def test_registry_is_singleton_behavior(self):
        """Test that the registry instance behaves like a singleton."""
        from protean.port.provider import registry as reg1
        from protean.port.provider import registry as reg2

        assert reg1 is reg2

        reg1.register("test", "path.to.Test")
        assert "test" in reg2._providers

    def test_registry_accessible_from_adapters_package(self):
        """Test that registry can be imported from adapters.repository."""
        from protean.adapters.repository import registry as adapter_registry
        from protean.port.provider import registry as port_registry

        assert adapter_registry is port_registry

    def test_entry_points_group_is_protean_providers(self):
        """Test that discovery uses the correct entry points group."""
        ProviderRegistry._initialized = False

        with patch("importlib.metadata.entry_points") as mock_entry_points:
            mock_eps = Mock()
            mock_eps.select.return_value = []
            mock_entry_points.return_value = mock_eps

            registry._discover_plugins()

            mock_eps.select.assert_called_once_with(group="protean.providers")
