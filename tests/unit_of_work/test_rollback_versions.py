"""How a rollback leaves a saved aggregate's versions, by provider capability."""

from unittest.mock import PropertyMock, patch

import pytest

from protean.adapters.repository.memory import MemorySession
from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import TransactionError
from protean.fields import Integer, String
from protean.port.provider import DatabaseCapabilities


class Tally(BaseAggregate):
    name: String(max_length=50)
    value: Integer(default=0)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Tally)
    test_domain.init(traverse=False)


def _saved_tally(test_domain):
    tally = Tally(name="t", value=0)
    with UnitOfWork():
        test_domain.repository_for(Tally).add(tally)
    return tally


def _add_and_roll_back(test_domain, tally):
    tally.value += 1
    with pytest.raises(RuntimeError, match="abort"), UnitOfWork():
        test_domain.repository_for(Tally).add(tally)
        raise RuntimeError("abort")


def test_rollback_restores_versions_when_the_provider_undoes_the_write(test_domain):
    tally = _saved_tally(test_domain)

    _add_and_roll_back(test_domain, tally)

    assert tally._version == 0
    assert tally._next_version == 1


def test_rollback_keeps_the_written_version_when_the_provider_has_no_transactions(
    test_domain,
):
    tally = _saved_tally(test_domain)
    provider_cls = type(test_domain.providers["default"])

    with patch.object(
        provider_cls,
        "capabilities",
        new_callable=PropertyMock,
        return_value=DatabaseCapabilities.BASIC_STORAGE,
    ):
        _add_and_roll_back(test_domain, tally)

    assert tally._version == 1
    assert tally._next_version == 2


def test_failure_in_a_later_provider_keeps_the_earlier_provider_committed(
    test_domain,
):
    class Counter(BaseAggregate):
        value: Integer(default=0)

    test_domain.config["databases"]["secondary"] = {"provider": "memory"}
    test_domain._initialize()
    test_domain.register(Counter, provider="secondary")
    test_domain.init(traverse=False)

    tally = _saved_tally(test_domain)
    counter = Counter(value=0)
    with UnitOfWork():
        test_domain.repository_for(Counter).add(counter)

    original_commit = MemorySession.commit

    def fail_on_secondary(session):
        if session._provider.name == "secondary":
            raise RuntimeError("secondary down")
        original_commit(session)

    tally.value += 1
    counter.value += 1
    with (
        patch.object(MemorySession, "commit", autospec=True) as commit,
        pytest.raises(TransactionError, match="secondary down"),
        UnitOfWork(),
    ):
        commit.side_effect = fail_on_secondary
        test_domain.repository_for(Tally).add(tally)
        test_domain.repository_for(Counter).add(counter)

    # The default provider committed before the secondary failed.
    assert test_domain.repository_for(Tally).get(tally.id)._version == 1
    assert tally._version == 1
    assert tally._next_version == 2

    assert test_domain.repository_for(Counter).get(counter.id)._version == 0
    assert counter._version == 0
    assert counter._next_version == 1
