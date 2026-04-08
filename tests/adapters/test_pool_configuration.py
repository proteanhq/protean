"""Tests for connection pool configuration across all adapters.

These tests verify that:
- Pool configuration parameters from conn_info/domain.toml are forwarded
  to the underlying client libraries (Redis, MessageDB, SQLAlchemy)
- Production-sensible defaults are applied
- Low pool_size triggers a warning during domain validation
"""

from unittest.mock import patch

import pytest

from protean import Domain
from protean.adapters.broker.redis import RedisBroker
from protean.adapters.cache.redis import RedisCache
from tests.shared import REDIS_URI


class TestRedisBrokerPoolConfig:
    """Verify that Redis broker forwards pool params from conn_info."""

    def test_pool_keys_extracted_from_conn_info(self, test_domain):
        """Pool-related keys should be extracted from conn_info."""
        conn_info = {
            "URI": "redis://localhost:6379/0",
            "max_connections": 20,
            "socket_timeout": 5.0,
            "socket_connect_timeout": 2.0,
            "retry_on_timeout": True,
        }
        with patch("redis.Redis.from_url"):
            broker = RedisBroker("test", test_domain, conn_info)

        assert broker._pool_kwargs == {
            "max_connections": 20,
            "socket_timeout": 5.0,
            "socket_connect_timeout": 2.0,
            "retry_on_timeout": True,
        }

    def test_non_pool_keys_excluded(self, test_domain):
        """Non-pool keys like URI should not leak into pool kwargs."""
        conn_info = {
            "URI": "redis://localhost:6379/0",
            "max_connections": 10,
        }
        with patch("redis.Redis.from_url"):
            broker = RedisBroker("test", test_domain, conn_info)

        assert "URI" not in broker._pool_kwargs

    def test_pool_kwargs_passed_to_from_url(self, test_domain):
        """Pool kwargs should be forwarded to redis.Redis.from_url()."""
        conn_info = {
            "URI": "redis://localhost:6379/0",
            "max_connections": 15,
            "socket_timeout": 3.0,
        }
        with patch("redis.Redis.from_url") as mock_from_url:
            RedisBroker("test", test_domain, conn_info)

        mock_from_url.assert_called_once_with(
            "redis://localhost:6379/0",
            max_connections=15,
            socket_timeout=3.0,
        )

    def test_no_pool_keys_means_no_extra_kwargs(self, test_domain):
        """When no pool keys are in conn_info, from_url is called with URI only."""
        conn_info = {"URI": "redis://localhost:6379/0"}
        with patch("redis.Redis.from_url") as mock_from_url:
            RedisBroker("test", test_domain, conn_info)

        mock_from_url.assert_called_once_with("redis://localhost:6379/0")

    def test_reconnect_uses_same_pool_kwargs(self, test_domain):
        """_ensure_connection reconnect should use the same pool kwargs."""
        conn_info = {
            "URI": "redis://localhost:6379/0",
            "max_connections": 25,
        }
        with patch("redis.Redis.from_url") as mock_from_url:
            broker = RedisBroker("test", test_domain, conn_info)

            # Simulate a failed ping followed by successful reconnect
            mock_instance = mock_from_url.return_value
            mock_instance.ping.side_effect = [ConnectionError, True]

            broker._ensure_connection()

            # Second call (reconnect) should include pool kwargs
            assert mock_from_url.call_count == 2
            reconnect_call = mock_from_url.call_args_list[1]
            assert reconnect_call.kwargs == {"max_connections": 25}

    @pytest.mark.redis
    def test_redis_broker_with_max_connections(self, test_domain):
        """Integration: Redis broker should accept max_connections in real use."""
        domain = Domain("Pool Config Broker Test")
        domain.config["brokers"]["default"] = {
            "provider": "redis",
            "URI": f"{REDIS_URI}/2",
            "max_connections": 10,
        }
        domain.init(traverse=False)

        try:
            with domain.domain_context():
                broker = domain.brokers["default"]
                assert broker._pool_kwargs == {"max_connections": 10}
                assert broker._ping() is True
        finally:
            for b in domain.brokers.values():
                b.close()


class TestRedisCachePoolConfig:
    """Verify that Redis cache forwards pool params from conn_info."""

    def test_pool_keys_extracted(self, test_domain):
        """Pool-related keys should be extracted from conn_info."""
        conn_info = {
            "URI": "redis://localhost:6379/0",
            "max_connections": 10,
            "socket_timeout": 5.0,
        }
        with patch("redis.Redis.from_url") as mock_from_url:
            RedisCache("test", test_domain, conn_info)

        mock_from_url.assert_called_once_with(
            "redis://localhost:6379/0",
            max_connections=10,
            socket_timeout=5.0,
        )

    def test_no_pool_keys_means_no_extra_kwargs(self, test_domain):
        """When no pool keys are in conn_info, from_url is called with URI only."""
        conn_info = {"URI": "redis://localhost:6379/0"}
        with patch("redis.Redis.from_url") as mock_from_url:
            RedisCache("test", test_domain, conn_info)

        mock_from_url.assert_called_once_with("redis://localhost:6379/0")


class TestMessageDBPoolConfig:
    """Verify that MessageDB forwards pool params from conn_info."""

    def test_pool_kwargs_extracted(self, test_domain):
        """max_connections should be extracted from conn_info."""
        from protean.adapters.event_store.message_db import MessageDBStore

        store = MessageDBStore(
            test_domain,
            {
                "database_uri": "postgresql://message_store@localhost:55433/message_store",
                "max_connections": 50,
            },
        )
        assert store._pool_kwargs == {"max_connections": 50}

    def test_non_pool_keys_excluded(self, test_domain):
        """Non-pool keys should not leak into pool kwargs."""
        from protean.adapters.event_store.message_db import MessageDBStore

        store = MessageDBStore(
            test_domain,
            {
                "database_uri": "postgresql://localhost/message_store",
                "max_connections": 50,
            },
        )
        assert "database_uri" not in store._pool_kwargs

    @pytest.mark.message_db
    def test_message_db_with_max_connections(self, test_domain):
        """Integration: MessageDB should accept max_connections in real use."""
        from protean.adapters.event_store.message_db import MessageDBStore

        store = MessageDBStore(
            test_domain,
            {
                "database_uri": "postgresql://message_store@localhost:55433/message_store",
                "max_connections": 20,
            },
        )
        # Trigger lazy client creation
        client = store.client
        assert client is not None
        store.close()


class TestSQLAlchemyPoolDefaults:
    """Verify that SQLAlchemy providers use production-sensible pool defaults."""

    def test_postgresql_default_pool_size(self, test_domain):
        """PostgreSQL provider should default to pool_size=5."""
        from protean.adapters.repository.sqlalchemy import PostgresqlProvider

        args = PostgresqlProvider._get_database_specific_engine_args(None)
        assert args["pool_size"] == 5

    def test_postgresql_default_max_overflow(self, test_domain):
        """PostgreSQL provider should default to max_overflow=10."""
        from protean.adapters.repository.sqlalchemy import PostgresqlProvider

        args = PostgresqlProvider._get_database_specific_engine_args(None)
        assert args["max_overflow"] == 10

    def test_mssql_default_pool_size(self, test_domain):
        """MSSQL provider should default to pool_size=5."""
        from protean.adapters.repository.sqlalchemy import MssqlProvider

        args = MssqlProvider._get_database_specific_engine_args(None)
        assert args["pool_size"] == 5

    def test_mssql_default_max_overflow(self, test_domain):
        """MSSQL provider should default to max_overflow=10."""
        from protean.adapters.repository.sqlalchemy import MssqlProvider

        args = MssqlProvider._get_database_specific_engine_args(None)
        assert args["max_overflow"] == 10

    def test_pool_pre_ping_enabled_by_default(self, test_domain):
        """PostgreSQL and MSSQL should have pool_pre_ping enabled."""
        from protean.adapters.repository.sqlalchemy import (
            MssqlProvider,
            PostgresqlProvider,
        )

        assert (
            PostgresqlProvider._get_database_specific_engine_args(None)["pool_pre_ping"]
            is True
        )
        assert (
            MssqlProvider._get_database_specific_engine_args(None)["pool_pre_ping"]
            is True
        )


@pytest.mark.no_test_domain
class TestLowPoolSizeWarning:
    """Verify that low pool_size emits a warning during domain validation."""

    def test_warning_emitted_for_low_pool_size(self):
        """pool_size < 5 should produce a LOW_POOL_SIZE warning."""
        domain = Domain("Low Pool Warning Test")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://user:pass@localhost/testdb",
            "pool_size": 2,
        }
        # Run validation without init (we don't need real DB connection)
        domain._validator._warn_low_pool_size()

        warnings = domain._validator.warnings
        assert any(w["code"] == "LOW_POOL_SIZE" for w in warnings)

    def test_no_warning_for_default_pool_size(self):
        """pool_size >= 5 should not produce a warning."""
        domain = Domain("Default Pool Test")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://user:pass@localhost/testdb",
            "pool_size": 5,
        }
        domain._validator._warn_low_pool_size()

        warnings = domain._validator.warnings
        assert not any(w["code"] == "LOW_POOL_SIZE" for w in warnings)

    def test_no_warning_for_memory_provider(self):
        """Memory provider should not trigger pool warnings."""
        domain = Domain("Memory Pool Test")
        domain.config["databases"]["default"] = {
            "provider": "memory",
            "pool_size": 1,
        }
        domain._validator._warn_low_pool_size()

        warnings = domain._validator.warnings
        assert not any(w["code"] == "LOW_POOL_SIZE" for w in warnings)

    def test_no_warning_when_pool_size_not_specified(self):
        """No warning when pool_size is not explicitly set in config."""
        domain = Domain("No Pool Size Test")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://user:pass@localhost/testdb",
        }
        domain._validator._warn_low_pool_size()

        warnings = domain._validator.warnings
        assert not any(w["code"] == "LOW_POOL_SIZE" for w in warnings)

    def test_warning_message_includes_db_name(self):
        """Warning message should identify which database has low pool_size."""
        domain = Domain("Named DB Test")
        domain.config["databases"]["analytics"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://user:pass@localhost/analytics",
            "pool_size": 1,
        }
        domain._validator._warn_low_pool_size()

        warnings = [
            w for w in domain._validator.warnings if w["code"] == "LOW_POOL_SIZE"
        ]
        assert len(warnings) == 1
        assert "analytics" in warnings[0]["message"]

    def test_non_dict_database_config_skipped(self):
        """Non-dict values in databases config should be silently skipped."""
        domain = Domain("Non-Dict DB Test")
        domain.config["databases"]["broken"] = "not-a-dict"
        domain._validator._warn_low_pool_size()

        warnings = domain._validator.warnings
        assert not any(w["code"] == "LOW_POOL_SIZE" for w in warnings)
