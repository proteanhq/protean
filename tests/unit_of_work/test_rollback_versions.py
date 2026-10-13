"""How a rollback leaves a saved aggregate's versions, by provider capability."""

from unittest.mock import PropertyMock, patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
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
