import pytest

from protean.adapters.repository import Providers
from protean.core.aggregate import BaseAggregate
from protean.fields import String
from protean.port.provider import BaseProvider


class User(BaseAggregate):
    name: String(required=True)
    email: String(required=True)


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

    def test_data_reset_clears_persisted_data(self, test_domain):
        """_data_reset flushes data so previously persisted records
        are no longer retrievable."""
        test_domain.register(User)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            test_domain.repository_for(User).add(
                User(name="Alice", email="alice@example.com")
            )
            assert test_domain.repository_for(User)._dao.query.all().total == 1

            provider = test_domain.providers["default"]
            provider._data_reset()

            assert test_domain.repository_for(User)._dao.query.all().total == 0

    def test_create_database_artifacts_is_idempotent(self, test_domain):
        """Calling _create_database_artifacts multiple times does not error."""
        test_domain.register(User)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            provider = test_domain.providers["default"]
            # Should not raise on repeated calls
            provider._create_database_artifacts()
            provider._create_database_artifacts()

    def test_domain_setup_database_delegates_to_provider(self, test_domain):
        """domain.setup_database() delegates to provider._create_database_artifacts()."""
        test_domain.register(User)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            # setup_database should succeed without error
            test_domain.setup_database()

            # Verify we can persist and retrieve data afterward
            test_domain.repository_for(User).add(
                User(name="Bob", email="bob@example.com")
            )
            assert test_domain.repository_for(User)._dao.query.all().total == 1

    def test_domain_truncate_database_delegates_to_provider(self, test_domain):
        """domain.truncate_database() delegates to provider._data_reset()."""
        test_domain.register(User)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            test_domain.repository_for(User).add(
                User(name="Charlie", email="charlie@example.com")
            )
            assert test_domain.repository_for(User)._dao.query.all().total == 1

            test_domain.truncate_database()

            assert test_domain.repository_for(User)._dao.query.all().total == 0

    def test_domain_drop_database_delegates_to_provider(self, test_domain):
        """domain.drop_database() delegates to provider._drop_database_artifacts()."""
        test_domain.register(User)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            # Should succeed without error
            test_domain.drop_database()
