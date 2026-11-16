"""What `ProviderPort` and `RawQueryProviderPort` require of a database adapter.

The stubs take their member set from each port's `__abstractmethods__`, so a
member added to a port later cannot make a missing-member case fail for the
wrong reason.
"""

from typing import Any

import pytest

from protean.adapters.repository.elasticsearch import ESProvider
from protean.adapters.repository.memory import MemoryProvider
from protean.adapters.repository.sqlalchemy import (
    MssqlProvider,
    MysqlProvider,
    PostgresqlProvider,
    SqliteProvider,
)
from protean.port.provider import BaseProvider, ProviderPort, RawQueryProviderPort

PROVIDER_PORT_MEMBERS = sorted(ProviderPort.__abstractmethods__)
SQL_PROVIDERS = [PostgresqlProvider, SqliteProvider, MssqlProvider, MysqlProvider]
CONCRETE_PROVIDERS = [MemoryProvider, ESProvider, *SQL_PROVIDERS]


def _stub_provider(port: type[ProviderPort], *, without: str | None = None) -> type:
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


class TestProviderPortIsEnforced:
    @pytest.mark.parametrize("member", PROVIDER_PORT_MEMBERS)
    def test_an_adapter_missing_a_member_cannot_be_built(self, member):
        with pytest.raises(TypeError, match=member):
            _stub_provider(ProviderPort, without=member)("stub", None, {})

    def test_a_complete_adapter_can_be_built(self):
        _stub_provider(ProviderPort)("stub", None, {})

    @pytest.mark.parametrize("member", ["close", "create_schema", "drop_schema"])
    def test_optional_lifecycle_members_default_to_no_ops(self, member):
        assert member not in ProviderPort.__abstractmethods__
        provider = _stub_provider(ProviderPort)("stub", None, {})
        assert getattr(provider, member)() is None


class TestRawQueryProviderPortIsEnforced:
    def test_an_adapter_without_raw_cannot_be_built(self):
        with pytest.raises(TypeError, match="raw"):
            _stub_provider(RawQueryProviderPort, without="raw")("stub", None, {})

    def test_an_adapter_with_raw_can_be_built(self):
        provider = _stub_provider(RawQueryProviderPort)("stub", None, {})
        assert provider.raw("query") is None


class TestBaseProviderRequiresRawForTheRawQueryPort:
    def test_a_provider_naming_the_port_without_raw_cannot_be_defined(self):
        with pytest.raises(TypeError, match="ForgotRaw .* does not implement raw"):

            class ForgotRaw(BaseProvider, RawQueryProviderPort):
                pass

    def test_a_provider_naming_the_port_with_raw_can_be_defined(self):
        class WithRaw(BaseProvider, RawQueryProviderPort):
            def raw(self, query: Any, data: Any = None) -> Any:
                return [query]

        assert WithRaw.raw is not BaseProvider.raw

    def test_a_provider_without_the_port_keeps_the_raising_raw(self):
        class NoRaw(BaseProvider, ProviderPort):
            pass

        assert NoRaw.raw is BaseProvider.raw


class TestBuiltInProvidersImplementThePorts:
    @pytest.mark.parametrize("provider_cls", [MemoryProvider, *SQL_PROVIDERS])
    def test_raw_query_providers_implement_the_raw_query_port(self, provider_cls):
        assert RawQueryProviderPort in provider_cls.__mro__

    def test_elasticsearch_implements_only_the_base_port(self):
        assert ProviderPort in ESProvider.__mro__
        assert RawQueryProviderPort not in ESProvider.__mro__

    def test_elasticsearch_defines_no_raw_query_method(self):
        assert "raw" not in ESProvider.__dict__
        assert "_raw" not in ESProvider.__dict__

    def test_memory_provider_inherits_the_no_op_close(self):
        assert "close" not in MemoryProvider.__dict__

    @pytest.mark.parametrize("provider_cls", CONCRETE_PROVIDERS)
    def test_base_provider_precedes_the_port_in_the_mro(self, provider_cls):
        mro = provider_cls.__mro__
        assert mro.index(BaseProvider) < mro.index(ProviderPort)

    @pytest.mark.parametrize("provider_cls", CONCRETE_PROVIDERS)
    def test_built_in_providers_leave_no_member_abstract(self, provider_cls):
        assert provider_cls.__abstractmethods__ == frozenset()
