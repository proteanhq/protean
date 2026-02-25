"""Tests for capability-gated methods on BaseProvider and QuerySet.

Verifies that operations requiring specific capabilities raise
NotSupportedError when invoked on providers that lack those capabilities,
and succeed on providers that declare them.
"""

import logging
from unittest.mock import PropertyMock, patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import NotSupportedError
from protean.fields import Integer, String
from protean.port.provider import BaseProvider, DatabaseCapabilities


class Widget(BaseAggregate):
    name: String(max_length=100, required=True)
    weight: Integer(default=0)


class TestRawQueryCapabilityGating:
    """Test that raw() is gated by RAW_QUERIES capability."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Widget)
        test_domain.init(traverse=False)

    def test_provider_raw_succeeds_when_capable(self, test_domain):
        """Providers with RAW_QUERIES can call raw() without error."""
        provider = test_domain.providers["default"]
        if not provider.has_capability(DatabaseCapabilities.RAW_QUERIES):
            pytest.skip("Provider does not support RAW_QUERIES")

        # Should not raise — exact query format varies by adapter,
        # but the gate itself should let the call through.
        # Memory accepts JSON queries, SA accepts SQL strings.
        if provider.__class__.__name__ == "MemoryProvider":
            result = provider.raw('{"name":"nonexistent"}')
            assert isinstance(result, list)
        else:
            # For SQL providers, use a simple query
            result = provider.raw("SELECT 1")
            assert result is not None

    def test_provider_raw_raises_when_not_capable(self, test_domain):
        """Providers without RAW_QUERIES raise NotSupportedError from raw()."""
        provider = test_domain.providers["default"]
        if provider.has_capability(DatabaseCapabilities.RAW_QUERIES):
            pytest.skip(
                "Provider supports RAW_QUERIES — test needs a provider without it"
            )

        with pytest.raises(NotSupportedError, match="does not support raw queries"):
            provider.raw("SELECT 1")

    def test_queryset_raw_raises_when_not_capable(self, test_domain):
        """QuerySet.raw() raises NotSupportedError for providers without RAW_QUERIES."""
        provider = test_domain.providers["default"]
        if provider.has_capability(DatabaseCapabilities.RAW_QUERIES):
            pytest.skip(
                "Provider supports RAW_QUERIES — test needs a provider without it"
            )

        dao = test_domain.repository_for(Widget)._dao
        with pytest.raises(NotSupportedError, match="does not support raw queries"):
            dao.query.raw("SELECT * FROM widget")

    def test_queryset_raw_succeeds_when_capable(self, test_domain):
        """QuerySet.raw() works for providers with RAW_QUERIES."""
        provider = test_domain.providers["default"]
        if not provider.has_capability(DatabaseCapabilities.RAW_QUERIES):
            pytest.skip("Provider does not support RAW_QUERIES")

        # Create a record first
        test_domain.repository_for(Widget).add(Widget(name="Sprocket", weight=10))

        dao = test_domain.repository_for(Widget)._dao
        if provider.__class__.__name__ == "MemoryProvider":
            results = dao.query.raw('{"name":"Sprocket"}')
        else:
            schema_name = Widget.meta_.schema_name
            results = dao.query.raw(f"SELECT * FROM {schema_name}")

        assert results.total >= 1


class TestRawQueryErrorMessage:
    """Verify error messages include provider name and class."""

    def test_error_includes_provider_details(self):
        """NotSupportedError from raw() includes provider name and class name."""

        class NoRawProvider(BaseProvider):
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
            def _raw(self, query, data=None): ...
            def _data_reset(self) -> None: ...
            def _create_database_artifacts(self) -> None: ...
            def _drop_database_artifacts(self) -> None: ...

        provider = NoRawProvider("analytics", None, {})

        with pytest.raises(NotSupportedError) as exc_info:
            provider.raw("SELECT 1")

        msg = str(exc_info.value)
        assert "analytics" in msg
        assert "NoRawProvider" in msg
        assert "does not support raw queries" in msg

    def test_raw_is_no_longer_abstract(self):
        """raw() should be a concrete method, not abstract."""
        assert "raw" not in BaseProvider.__abstractmethods__

    def test_internal_raw_is_abstract(self):
        """_raw() should be declared as abstract."""
        assert "_raw" in BaseProvider.__abstractmethods__


class TestTransactionCapabilityWarnings:
    """Test that UoW.start() emits appropriate warnings for transaction capabilities."""

    def test_simulated_transactions_logs_debug(self, test_domain, caplog):
        """Provider with SIMULATED_TRANSACTIONS logs a debug message."""
        provider = test_domain.providers["default"]
        if not provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS):
            pytest.skip("Provider does not use simulated transactions")

        from protean.core.unit_of_work import UnitOfWork

        with caplog.at_level(logging.DEBUG, logger="protean.core.unit_of_work"):
            uow = UnitOfWork()
            uow.start()
            uow.rollback()

        assert any(
            "simulated transactions" in record.message for record in caplog.records
        )

    def test_no_transactions_logs_warning(self, test_domain, caplog):
        """Provider without TRANSACTIONS or SIMULATED_TRANSACTIONS logs a warning."""
        provider = test_domain.providers["default"]
        if provider.has_capability(
            DatabaseCapabilities.TRANSACTIONS
        ) or provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS):
            pytest.skip("Provider supports some form of transactions")

        from protean.core.unit_of_work import UnitOfWork

        with caplog.at_level(logging.WARNING, logger="protean.core.unit_of_work"):
            uow = UnitOfWork()
            uow.start()
            uow.rollback()

        assert any(
            "does not support transactions" in record.message
            for record in caplog.records
        )

    def test_real_transactions_no_warning(self, test_domain, caplog):
        """Provider with TRANSACTIONS should not emit any transaction warning."""
        provider = test_domain.providers["default"]
        if not provider.has_capability(DatabaseCapabilities.TRANSACTIONS):
            pytest.skip("Provider does not support real transactions")

        from protean.core.unit_of_work import UnitOfWork

        with caplog.at_level(logging.DEBUG, logger="protean.core.unit_of_work"):
            uow = UnitOfWork()
            uow.start()
            uow.rollback()

        transaction_messages = [
            record
            for record in caplog.records
            if "simulated transactions" in record.message
            or "does not support transactions" in record.message
        ]
        assert len(transaction_messages) == 0

    def test_real_transactions_skips_warning_branch(self, test_domain, caplog):
        """Force TRANSACTIONS capability to cover the no-warning branch (97->96)."""
        from protean.core.unit_of_work import UnitOfWork

        provider = test_domain.providers["default"]
        real_caps = DatabaseCapabilities.RELATIONAL  # includes TRANSACTIONS

        with (
            caplog.at_level(logging.DEBUG, logger="protean.core.unit_of_work"),
            patch.object(
                type(provider),
                "capabilities",
                new_callable=PropertyMock,
                return_value=real_caps,
            ),
        ):
            uow = UnitOfWork()
            uow.start()
            uow.rollback()

        transaction_messages = [
            record
            for record in caplog.records
            if "simulated transactions" in record.message
            or "does not support transactions" in record.message
        ]
        assert len(transaction_messages) == 0


class TestQuerySetRawCapabilityGatingForced:
    """Force the RAW_QUERIES guard in QuerySet.raw() to cover line 291."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Widget)
        test_domain.init(traverse=False)

    def test_queryset_raw_raises_when_capability_removed(self, test_domain):
        """QuerySet.raw() raises NotSupportedError when provider lacks RAW_QUERIES."""
        dao = test_domain.repository_for(Widget)._dao
        provider = dao.provider

        # Strip RAW_QUERIES from the provider's capabilities
        caps_without_raw = provider.capabilities & ~DatabaseCapabilities.RAW_QUERIES

        with (
            patch.object(
                type(provider),
                "capabilities",
                new_callable=PropertyMock,
                return_value=caps_without_raw,
            ),
            pytest.raises(NotSupportedError, match="does not support raw queries"),
        ):
            dao.query.raw("SELECT * FROM widget")
