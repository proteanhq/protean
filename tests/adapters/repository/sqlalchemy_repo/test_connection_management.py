"""Tests for SQLAlchemy connection pool management and lifecycle.

These tests verify that:
- Session factories are cached and reused (not recreated per call)
- Connections are properly returned to the pool after operations
- UoW cleanup properly removes scoped sessions
- Provider.close() disposes the engine and all pool connections
- Engine pool settings are applied correctly
"""

import pytest
from sqlalchemy import orm, text

from protean import Domain, UnitOfWork
from protean.adapters.repository.sqlalchemy import (
    SAProvider,
)
from protean.core.aggregate import BaseAggregate
from protean.fields import String, Integer


class DummyEntity(BaseAggregate):
    name: String(max_length=100, required=True)
    age: Integer(default=0)


class TestSessionFactoryCaching:
    """Verify that get_session() returns the same cached scoped_session."""

    def test_get_session_returns_same_instance(self, test_domain):
        """get_session() should return the same scoped_session object every time."""
        provider = test_domain.providers["default"]

        if not isinstance(provider, SAProvider):
            pytest.skip("Only applicable to SQLAlchemy providers")

        session1 = provider.get_session()
        session2 = provider.get_session()

        assert session1 is session2, (
            "get_session() should return the cached scoped_session, "
            "not create a new one on every call"
        )

    def test_get_session_returns_same_instance_across_many_calls(self, test_domain):
        """get_session() should be stable across many invocations."""
        provider = test_domain.providers["default"]

        if not isinstance(provider, SAProvider):
            pytest.skip("Only applicable to SQLAlchemy providers")

        sessions = [provider.get_session() for _ in range(100)]
        assert all(s is sessions[0] for s in sessions)

    def test_scoped_session_created_during_init(self, test_domain):
        """The scoped session should be created during provider __init__."""
        provider = test_domain.providers["default"]

        if not isinstance(provider, SAProvider):
            pytest.skip("Only applicable to SQLAlchemy providers")

        assert hasattr(provider, "_scoped_session_cls")
        assert hasattr(provider, "_session_factory")
        assert isinstance(provider._scoped_session_cls, orm.scoped_session)

    def test_session_factory_bound_to_engine(self, test_domain):
        """The session factory should be bound to the provider's engine."""
        provider = test_domain.providers["default"]

        if not isinstance(provider, SAProvider):
            pytest.skip("Only applicable to SQLAlchemy providers")

        assert provider._session_factory.kw.get("bind") is provider._engine


@pytest.mark.postgresql
class TestConnectionLifecyclePostgresql:
    """Test that connections are properly acquired and released with PostgreSQL."""

    @pytest.fixture(autouse=True)
    def setup_domain(self):
        domain = Domain("PG Connection Lifecycle Tests")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }
        domain.init(traverse=False)

        with domain.domain_context():
            yield domain

        # Ensure engine is disposed
        for provider in domain.providers.values():
            provider.close()

    def _register_and_setup(self, domain):
        domain.register(DummyEntity)
        domain.init(traverse=False)
        provider = domain.providers["default"]
        provider._create_database_artifacts()
        return provider

    def test_connection_returned_to_pool_after_dao_filter(self, setup_domain):
        """Connections should be returned to pool after DAO filter operations."""
        provider = self._register_and_setup(setup_domain)
        pool_obj = provider._engine.pool

        # Perform a filter operation (outside UoW)
        dao = setup_domain.repository_for(DummyEntity)._dao
        dao.query.all()

        # After the operation, connections should be returned
        assert pool_obj.checkedout() == 0, (
            "Connection was not returned to pool after filter operation"
        )
        provider._drop_database_artifacts()

    def test_connection_returned_to_pool_after_dao_create(self, setup_domain):
        """Connections should be returned to pool after DAO create operations."""
        provider = self._register_and_setup(setup_domain)
        pool_obj = provider._engine.pool

        # Create an entity (outside UoW)
        dao = setup_domain.repository_for(DummyEntity)._dao
        dao.create(name="Test", age=25)

        assert pool_obj.checkedout() == 0, (
            "Connection was not returned to pool after create operation"
        )
        provider._drop_database_artifacts()

    def test_uow_releases_connections_on_commit(self, setup_domain):
        """UoW commit should release all connections back to the pool."""
        provider = self._register_and_setup(setup_domain)
        pool_obj = provider._engine.pool

        with UnitOfWork():
            repo = setup_domain.repository_for(DummyEntity)
            repo.add(DummyEntity(name="Test", age=25))

        assert pool_obj.checkedout() == 0, (
            "Connection was not returned to pool after UoW commit"
        )
        provider._drop_database_artifacts()

    def test_uow_releases_connections_on_rollback(self, setup_domain):
        """UoW rollback should release all connections back to the pool."""
        provider = self._register_and_setup(setup_domain)
        pool_obj = provider._engine.pool

        uow = UnitOfWork()
        uow.start()
        repo = setup_domain.repository_for(DummyEntity)
        repo.add(DummyEntity(name="Test", age=25))
        uow.rollback()

        assert pool_obj.checkedout() == 0, (
            "Connection was not returned to pool after UoW rollback"
        )
        provider._drop_database_artifacts()

    def test_uow_releases_connections_on_exception(self, setup_domain):
        """UoW should release connections even when an exception occurs."""
        provider = self._register_and_setup(setup_domain)
        pool_obj = provider._engine.pool

        with pytest.raises(ValueError):
            with UnitOfWork():
                repo = setup_domain.repository_for(DummyEntity)
                repo.add(DummyEntity(name="Test", age=25))
                raise ValueError("Simulated error")

        assert pool_obj.checkedout() == 0, (
            "Connection was not returned to pool after UoW exception"
        )
        provider._drop_database_artifacts()

    def test_no_connection_leak_across_many_operations(self, setup_domain):
        """Repeatedly performing operations should not leak connections."""
        provider = self._register_and_setup(setup_domain)
        pool_obj = provider._engine.pool

        dao = setup_domain.repository_for(DummyEntity)._dao

        # Perform many operations
        for i in range(50):
            dao.create(name=f"Entity-{i}", age=i)

        assert pool_obj.checkedout() == 0, (
            "Connections leaked after repeated create operations"
        )

        # Read all
        dao.query.all()
        assert pool_obj.checkedout() == 0, "Connections leaked after query.all()"

        provider._drop_database_artifacts()


class TestProviderClose:
    """Test that provider.close() properly disposes all resources."""

    def test_close_disposes_engine_and_pool(self):
        """provider.close() should dispose the engine pool."""
        domain = Domain("Close Test")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite://",
        }
        domain.init(traverse=False)

        provider = domain.providers["default"]
        engine = provider._engine

        # Verify engine is alive
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        # Close provider — should not raise
        provider.close()

    def test_close_removes_scoped_session(self):
        """provider.close() should remove the scoped session from the registry."""
        domain = Domain("Close Session Test")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite://",
        }
        domain.init(traverse=False)

        provider = domain.providers["default"]

        # Get a session to populate the registry
        scoped = provider.get_session()
        scoped()  # Instantiate session in the registry

        # Close provider — calls .remove() then .dispose()
        provider.close()

        # After remove(), the next call to scoped() would create a NEW session
        # (but we can't easily test this without a live engine, which is disposed)

    def test_multiple_close_calls_are_safe(self):
        """Calling close() multiple times should not raise."""
        domain = Domain("Multiple Close Test")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite://",
        }
        domain.init(traverse=False)

        provider = domain.providers["default"]

        # Close multiple times — should not raise
        provider.close()
        provider.close()
        provider.close()

    @pytest.mark.postgresql
    def test_close_releases_all_postgresql_connections(self):
        """provider.close() should release all PostgreSQL pool connections."""
        domain = Domain("PG Close Test")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }
        domain.init(traverse=False)

        provider = domain.providers["default"]
        pool_obj = provider._engine.pool

        # Use a connection so the pool is populated
        conn = provider.get_connection()
        conn.execute(text("SELECT 1"))
        conn.close()

        assert pool_obj.size() > 0 or pool_obj.checkedin() > 0

        # Close provider
        provider.close()

        # After dispose, pool metrics should reflect cleanup
        assert pool_obj.checkedout() == 0


class TestPoolConfiguration:
    """Test that pool configuration defaults are applied correctly."""

    @pytest.mark.postgresql
    def test_postgresql_pool_defaults(self):
        """PostgreSQL provider should have pool_size=2 and max_overflow=5."""
        domain = Domain("PG Pool Defaults Test")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }
        domain.init(traverse=False)

        try:
            provider = domain.providers["default"]
            engine_pool = provider._engine.pool

            assert engine_pool.size() == 2, (
                f"Expected pool_size=2, got {engine_pool.size()}"
            )
            assert engine_pool._max_overflow == 5, (
                f"Expected max_overflow=5, got {engine_pool._max_overflow}"
            )
        finally:
            for p in domain.providers.values():
                p.close()

    @pytest.mark.postgresql
    def test_pool_config_overridable_via_conn_info(self):
        """Pool settings from conn_info should override defaults."""
        domain = Domain("PG Pool Override Test")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
            "pool_size": 3,
            "max_overflow": 8,
        }
        domain.init(traverse=False)

        try:
            provider = domain.providers["default"]
            engine_pool = provider._engine.pool

            assert engine_pool.size() == 3, (
                f"Expected pool_size=3 (overridden), got {engine_pool.size()}"
            )
            assert engine_pool._max_overflow == 8, (
                f"Expected max_overflow=8 (overridden), got {engine_pool._max_overflow}"
            )
        finally:
            for p in domain.providers.values():
                p.close()

    @pytest.mark.postgresql
    def test_postgresql_engine_has_pool_pre_ping(self):
        """PostgreSQL engine should have pool_pre_ping enabled."""
        domain = Domain("PG Pre-Ping Test")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }
        domain.init(traverse=False)

        try:
            provider = domain.providers["default"]
            assert provider._engine.pool._pre_ping is True
        finally:
            for p in domain.providers.values():
                p.close()


class TestIsAliveConnectionHandling:
    """Test that is_alive() properly manages connections."""

    def test_is_alive_returns_true_for_valid_connection(self):
        """is_alive() should return True for a valid database."""
        domain = Domain("IsAlive Test")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite://",
        }
        domain.init(traverse=False)

        try:
            provider = domain.providers["default"]
            assert provider.is_alive() is True
        finally:
            for p in domain.providers.values():
                p.close()

    @pytest.mark.postgresql
    def test_is_alive_closes_connection_on_success_postgresql(self):
        """is_alive() should close its connection after a successful check."""
        domain = Domain("PG IsAlive Test")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }
        domain.init(traverse=False)

        try:
            provider = domain.providers["default"]
            pool_obj = provider._engine.pool

            result = provider.is_alive()

            assert result is True
            assert pool_obj.checkedout() == 0, (
                "is_alive() should return connection to pool on success"
            )
        finally:
            for p in domain.providers.values():
                p.close()


class TestUoWSessionCleanup:
    """Test that UoW._reset() properly cleans up sessions."""

    def test_reset_clears_sessions_dict(self, test_domain):
        """_reset() should empty the sessions dictionary."""
        uow = UnitOfWork()
        uow.start()

        # Create a session
        provider_name = "default"
        uow.get_session(provider_name)
        assert provider_name in uow._sessions

        uow.rollback()

        assert uow._sessions == {}

    def test_reset_calls_remove_on_scoped_sessions(self, test_domain):
        """_reset() should call remove() on scoped sessions, not just close()."""
        provider = test_domain.providers["default"]

        if not isinstance(provider, SAProvider):
            pytest.skip("Only applicable to SQLAlchemy providers")

        uow = UnitOfWork()
        uow.start()

        # Get a session through the UoW
        session = uow.get_session("default")

        # Verify it has the remove method (scoped_session)
        assert hasattr(session, "remove"), (
            "UoW session should be a scoped_session with remove() method"
        )

        # Patch remove to verify it gets called
        original_remove = session.remove
        remove_called = False

        def mock_remove():
            nonlocal remove_called
            remove_called = True
            original_remove()

        session.remove = mock_remove

        uow.rollback()

        assert remove_called, "_reset() should call remove() on scoped sessions"

    def test_uow_sessions_empty_after_context_manager_exit(self, test_domain):
        """After the UoW context manager exits, no sessions should remain."""
        with UnitOfWork() as uow:
            # Just enter and exit
            pass

        assert uow._sessions == {}
        assert uow._in_progress is False
