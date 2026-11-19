"""What `DatabasePort` and `RawQueryDatabasePort` require of a database adapter.

The stubs take their member set from each port's `__abstractmethods__`, so a
member added to a port later cannot make a missing-member case fail for the
wrong reason.
"""

from typing import Any

import pytest

from protean.adapters.database.elasticsearch import ESDatabase
from protean.adapters.database.memory import MemoryDatabase
from protean.adapters.database.sqlalchemy import (
    MssqlDatabase,
    MysqlDatabase,
    PostgresqlDatabase,
    SqliteDatabase,
)
from protean.port.database import BaseDatabase, DatabasePort, RawQueryDatabasePort

PROVIDER_PORT_MEMBERS = sorted(DatabasePort.__abstractmethods__)
SQL_PROVIDERS = [PostgresqlDatabase, SqliteDatabase, MssqlDatabase, MysqlDatabase]
CONCRETE_PROVIDERS = [MemoryDatabase, ESDatabase, *SQL_PROVIDERS]


def _stub_provider(port: type[DatabasePort], *, without: str | None = None) -> type:
    """A subclass of `port` that implements every abstract member except
    `without`."""
    members: dict[str, Any] = {
        name: (lambda self, *args, **kwargs: None)
        for name in port.__abstractmethods__
        if name != without
    }
    if "capabilities" in members:
        members["capabilities"] = property(lambda self: None)
    return type("StubProvider", (port,), members)


def test_provider_port_declares_the_expected_abstract_members():
    assert PROVIDER_PORT_MEMBERS == [
        "capabilities",
        "clear",
        "commit",
        "dao_for",
        "get_connection",
        "get_lookup",
        "get_lookups",
        "get_session",
        "health",
        "model_for",
        "new_session",
        "ping",
        "rollback",
    ]


class TestDatabasePortIsEnforced:
    @pytest.mark.parametrize("member", PROVIDER_PORT_MEMBERS)
    def test_an_adapter_missing_a_member_cannot_be_built(self, member):
        with pytest.raises(TypeError, match=member):
            _stub_provider(DatabasePort, without=member)("stub", None, {})

    def test_a_complete_adapter_can_be_built(self):
        _stub_provider(DatabasePort)("stub", None, {})

    @pytest.mark.parametrize("member", ["close", "create_schema", "drop_schema"])
    def test_optional_lifecycle_members_default_to_no_ops(self, member):
        assert member not in DatabasePort.__abstractmethods__
        provider = _stub_provider(DatabasePort)("stub", None, {})
        assert getattr(provider, member)() is None


class TestRawQueryDatabasePortIsEnforced:
    def test_an_adapter_without_raw_cannot_be_built(self):
        with pytest.raises(TypeError, match="raw"):
            _stub_provider(RawQueryDatabasePort, without="raw")("stub", None, {})

    def test_an_adapter_with_raw_can_be_built(self):
        provider = _stub_provider(RawQueryDatabasePort)("stub", None, {})
        assert provider.raw("query") is None


class TestBaseDatabaseRequiresRawForTheRawQueryPort:
    def test_a_provider_naming_the_port_without_raw_cannot_be_defined(self):
        with pytest.raises(TypeError, match="ForgotRaw .* does not implement raw"):

            class ForgotRaw(BaseDatabase, RawQueryDatabasePort):
                pass

    def test_a_provider_naming_the_port_with_raw_can_be_defined(self):
        class WithRaw(BaseDatabase, RawQueryDatabasePort):
            def raw(self, query: Any, data: Any = None) -> Any:
                return [query]

        assert WithRaw.raw is not BaseDatabase.raw

    def test_a_provider_without_the_port_keeps_the_raising_raw(self):
        class NoRaw(BaseDatabase, DatabasePort):
            pass

        assert NoRaw.raw is BaseDatabase.raw


class TestBuiltInProvidersImplementThePorts:
    @pytest.mark.parametrize("provider_cls", [MemoryDatabase, *SQL_PROVIDERS])
    def test_raw_query_providers_implement_the_raw_query_port(self, provider_cls):
        assert RawQueryDatabasePort in provider_cls.__mro__

    def test_elasticsearch_implements_only_the_base_port(self):
        assert DatabasePort in ESDatabase.__mro__
        assert RawQueryDatabasePort not in ESDatabase.__mro__

    def test_elasticsearch_defines_no_raw_query_method(self):
        assert "raw" not in ESDatabase.__dict__
        assert "_raw" not in ESDatabase.__dict__

    def test_memory_provider_inherits_the_no_op_close(self):
        assert "close" not in MemoryDatabase.__dict__

    @pytest.mark.parametrize("provider_cls", CONCRETE_PROVIDERS)
    def test_base_provider_precedes_the_port_in_the_mro(self, provider_cls):
        mro = provider_cls.__mro__
        assert mro.index(BaseDatabase) < mro.index(DatabasePort)

    @pytest.mark.parametrize("provider_cls", CONCRETE_PROVIDERS)
    def test_built_in_providers_leave_no_member_abstract(self, provider_cls):
        assert provider_cls.__abstractmethods__ == frozenset()
