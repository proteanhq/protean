# --8<-- [start:test]
import pytest

from protean.port.provider import DatabaseCapabilities


def test_every_adapter_reports_its_capabilities(adapter):
    assert isinstance(adapter.capabilities, DatabaseCapabilities)


@pytest.mark.requires(DatabaseCapabilities.CRUD)
def test_runs_when_the_adapter_declares_crud(adapter):
    assert DatabaseCapabilities.CRUD in adapter.capabilities


@pytest.mark.requires(DatabaseCapabilities.NATIVE_JSON)
def test_runs_only_on_adapters_with_native_json(adapter):
    assert DatabaseCapabilities.NATIVE_JSON in adapter.capabilities


@pytest.mark.requires_any(
    DatabaseCapabilities.TRANSACTIONS, DatabaseCapabilities.SIMULATED_TRANSACTIONS
)
def test_runs_when_the_adapter_declares_either_kind_of_transaction(adapter):
    assert adapter.capabilities & (
        DatabaseCapabilities.TRANSACTIONS | DatabaseCapabilities.SIMULATED_TRANSACTIONS
    )


# --8<-- [end:test]
