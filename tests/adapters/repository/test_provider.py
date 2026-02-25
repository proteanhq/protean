import pytest

from protean.adapters.repository import DATABASE_PROVIDERS, Providers
from protean.exceptions import ConfigurationError
from protean.port.provider import BaseProvider, DatabaseCapabilities


@pytest.mark.database
class TestBasicProvider:
    """Test basic provider functionality across SQLAlchemy databases"""

    def test_initialization_of_providers_on_first_call(self, test_domain):
        """Test that providers object is available"""
        assert isinstance(test_domain.providers, Providers)
        assert test_domain.providers._providers is not None
        assert "default" in test_domain.providers

    def test_connection_to_db_is_successful(self, test_domain):
        """Test connection to database"""
        provider = test_domain.providers["default"]
        assert provider.is_alive()

    def test_provider_name(self, test_domain):
        """Test that provider name is correctly set"""
        provider = test_domain.providers["default"]
        assert provider.name == "default"

    def test_provider_has_database_setting(self, test_domain):
        """Test that provider has a database setting"""
        provider = test_domain.providers["default"]
        assert hasattr(provider.__class__, "__database__")
        assert provider.__class__.__database__ is not None


class TestLifecycleMethodsAbstractContract:
    """Test that BaseProvider declares lifecycle methods as abstract."""

    def test_lifecycle_methods_are_abstract(self):
        """_data_reset, _create_database_artifacts, and _drop_database_artifacts
        must be declared as abstract methods on BaseProvider."""
        abstract_methods = BaseProvider.__abstractmethods__
        assert "_data_reset" in abstract_methods
        assert "_create_database_artifacts" in abstract_methods
        assert "_drop_database_artifacts" in abstract_methods

    def test_subclass_missing_data_reset_cannot_be_instantiated(self):
        """A provider subclass that omits _data_reset cannot be instantiated."""

        class IncompleteProvider(BaseProvider):
            @property
            def capabilities(self) -> DatabaseCapabilities:
                return DatabaseCapabilities.BASIC_STORAGE

            def get_session(self): ...
            def get_connection(self): ...
            def is_alive(self) -> bool: ...
            def close(self): ...
            def get_dao(self, entity_cls, database_model_cls): ...
            def decorate_database_model_class(self, entity_cls, database_model_cls): ...
            def construct_database_model_class(self, entity_cls): ...
            def raw(self, query, data=None): ...
            # _data_reset intentionally omitted
            def _create_database_artifacts(self) -> None: ...
            def _drop_database_artifacts(self) -> None: ...

        with pytest.raises(TypeError, match="_data_reset"):
            IncompleteProvider("test", None, {})

    def test_subclass_missing_create_artifacts_cannot_be_instantiated(self):
        """A provider subclass that omits _create_database_artifacts
        cannot be instantiated."""

        class IncompleteProvider(BaseProvider):
            @property
            def capabilities(self) -> DatabaseCapabilities:
                return DatabaseCapabilities.BASIC_STORAGE

            def get_session(self): ...
            def get_connection(self): ...
            def is_alive(self) -> bool: ...
            def close(self): ...
            def get_dao(self, entity_cls, database_model_cls): ...
            def decorate_database_model_class(self, entity_cls, database_model_cls): ...
            def construct_database_model_class(self, entity_cls): ...
            def raw(self, query, data=None): ...
            def _data_reset(self) -> None: ...
            # _create_database_artifacts intentionally omitted
            def _drop_database_artifacts(self) -> None: ...

        with pytest.raises(TypeError, match="_create_database_artifacts"):
            IncompleteProvider("test", None, {})

    def test_subclass_missing_drop_artifacts_cannot_be_instantiated(self):
        """A provider subclass that omits _drop_database_artifacts
        cannot be instantiated."""

        class IncompleteProvider(BaseProvider):
            @property
            def capabilities(self) -> DatabaseCapabilities:
                return DatabaseCapabilities.BASIC_STORAGE

            def get_session(self): ...
            def get_connection(self): ...
            def is_alive(self) -> bool: ...
            def close(self): ...
            def get_dao(self, entity_cls, database_model_cls): ...
            def decorate_database_model_class(self, entity_cls, database_model_cls): ...
            def construct_database_model_class(self, entity_cls): ...
            def raw(self, query, data=None): ...
            def _data_reset(self) -> None: ...
            def _create_database_artifacts(self) -> None: ...

            # _drop_database_artifacts intentionally omitted

        with pytest.raises(TypeError, match="_drop_database_artifacts"):
            IncompleteProvider("test", None, {})

    def test_complete_subclass_can_be_instantiated(self):
        """A provider subclass implementing all abstract methods
        can be instantiated successfully."""

        class CompleteProvider(BaseProvider):
            @property
            def capabilities(self) -> DatabaseCapabilities:
                return DatabaseCapabilities.BASIC_STORAGE

            def get_session(self): ...
            def get_connection(self): ...
            def is_alive(self) -> bool:
                return True

            def close(self): ...
            def get_dao(self, entity_cls, database_model_cls): ...
            def decorate_database_model_class(self, entity_cls, database_model_cls): ...
            def construct_database_model_class(self, entity_cls): ...
            def raw(self, query, data=None): ...
            def _data_reset(self) -> None: ...
            def _create_database_artifacts(self) -> None: ...
            def _drop_database_artifacts(self) -> None: ...

        provider = CompleteProvider("test", None, {})
        assert provider.name == "test"


@pytest.mark.database
class TestLifecycleMethodsIntegration:
    """Test that lifecycle methods work correctly through the domain."""

    def test_data_reset_clears_persisted_data(self, test_domain, user_cls):
        """_data_reset flushes data so previously persisted records
        are no longer retrievable."""
        test_domain.repository_for(user_cls).add(
            user_cls(name="Alice", email="alice@example.com")
        )
        assert test_domain.repository_for(user_cls)._dao.query.all().total == 1

        provider = test_domain.providers["default"]
        provider._data_reset()

        assert test_domain.repository_for(user_cls)._dao.query.all().total == 0

    def test_create_database_artifacts_is_idempotent(self, test_domain):
        """Calling _create_database_artifacts multiple times does not error."""
        provider = test_domain.providers["default"]
        # Should not raise on repeated calls
        provider._create_database_artifacts()
        provider._create_database_artifacts()

    def test_domain_setup_database_delegates_to_provider(self, test_domain, user_cls):
        """domain.setup_database() delegates to provider._create_database_artifacts()."""
        # setup_database should succeed without error (idempotent)
        test_domain.setup_database()

        # Verify we can persist and retrieve data afterward
        test_domain.repository_for(user_cls).add(
            user_cls(name="Bob", email="bob@example.com")
        )
        assert test_domain.repository_for(user_cls)._dao.query.all().total == 1

    def test_domain_truncate_database_delegates_to_provider(
        self, test_domain, user_cls
    ):
        """domain.truncate_database() delegates to provider._data_reset()."""
        test_domain.repository_for(user_cls).add(
            user_cls(name="Charlie", email="charlie@example.com")
        )
        assert test_domain.repository_for(user_cls)._dao.query.all().total == 1

        test_domain.truncate_database()

        assert test_domain.repository_for(user_cls)._dao.query.all().total == 0

    def test_domain_drop_database_delegates_to_provider(self, test_domain):
        """domain.drop_database() delegates to provider._drop_database_artifacts()."""
        # Should succeed without error
        test_domain.drop_database()


@pytest.mark.no_test_domain
class TestConfigurationErrorMessages:
    """Test that provider misconfiguration produces helpful error messages."""

    def test_unknown_provider_type_raises_with_available_list(self):
        """A typo in the provider name raises ConfigurationError listing available providers."""
        from protean.domain import Domain

        domain = Domain(name="TestBadProvider")
        domain.config["databases"] = {
            "default": {
                "provider": "postgresqll",  # typo
                "database_uri": "postgresql://localhost/test",
            }
        }

        with domain.domain_context():
            with pytest.raises(
                ConfigurationError, match="Unknown database provider"
            ) as exc_info:
                domain.providers._initialize()

            error_msg = str(exc_info.value)
            assert "'postgresqll'" in error_msg
            assert "Available providers:" in error_msg
            for name in sorted(DATABASE_PROVIDERS.keys()):
                assert name in error_msg

    def test_none_provider_type_raises_with_available_list(self):
        """Missing 'provider' key in config raises ConfigurationError."""
        from protean.domain import Domain

        domain = Domain(name="TestNoneProvider")
        domain.config["databases"] = {
            "default": {
                "database_uri": "memory://",
                # 'provider' key missing entirely
            }
        }

        with domain.domain_context():
            with pytest.raises(
                ConfigurationError, match="Unknown database provider"
            ) as exc_info:
                domain.providers._initialize()

            assert "'None'" in str(exc_info.value)

    def test_get_connection_unknown_name_raises_with_configured_list(self):
        """get_connection with unknown name raises ConfigurationError listing configured providers."""
        from protean.domain import Domain

        domain = Domain(name="TestUnknownConn")
        domain.config["databases"] = {
            "default": {
                "provider": "memory",
                "database_uri": "memory://",
            }
        }
        domain.init(traverse=False)

        with domain.domain_context():
            with pytest.raises(
                ConfigurationError, match="No provider configured"
            ) as exc_info:
                domain.providers.get_connection("nonexistent")

            error_msg = str(exc_info.value)
            assert "'nonexistent'" in error_msg
            assert "Configured providers:" in error_msg
            assert "default" in error_msg

    def test_repository_for_unknown_provider_raises_with_configured_list(self):
        """repository_for with aggregate pointing to unknown provider raises ConfigurationError."""
        from protean.core.aggregate import BaseAggregate
        from protean.domain import Domain
        from protean.fields import String

        domain = Domain(name="TestRepoProviderMismatch")
        domain.config["databases"] = {
            "default": {
                "provider": "memory",
                "database_uri": "memory://",
            }
        }

        class MismatchedAgg(BaseAggregate):
            name: String(max_length=50)

        domain.register(MismatchedAgg, provider="analytics")
        domain.init(traverse=False)

        with domain.domain_context():
            with pytest.raises(
                ConfigurationError, match="No provider configured"
            ) as exc_info:
                domain.providers.repository_for(MismatchedAgg)

            error_msg = str(exc_info.value)
            assert "'analytics'" in error_msg
            assert "Configured providers:" in error_msg
            assert "default" in error_msg

    def test_missing_default_provider_raises_configuration_error(self):
        """_initialize raises ConfigurationError when no 'default' provider."""
        from protean.domain import Domain

        domain = Domain(name="TestNoDefault")
        domain.config["databases"] = {
            "custom_only": {
                "provider": "memory",
                "database_uri": "memory://",
            }
        }

        with domain.domain_context():
            with pytest.raises(
                ConfigurationError, match="You must define a 'default' provider"
            ):
                domain.providers._initialize()
