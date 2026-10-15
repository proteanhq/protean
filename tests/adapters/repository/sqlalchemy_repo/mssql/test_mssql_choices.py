"""SQL Server needs a length on a key column, and a ``String`` with ``choices``
used to lose its ``max_length`` on the way to the column.

The provider is built without a connection, so these tests compile the table
and stop there. They need ``pyodbc``, which is why they sit in this directory.
"""

import pytest

from protean import Domain
from protean.adapters.repository.sqlalchemy import MssqlProvider
from protean.core.aggregate import BaseAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from tests.shared import MSSQL_URI

pytestmark = [pytest.mark.mssql, pytest.mark.no_test_domain]


def build_table(aggregate_cls):
    domain = Domain(
        name="MSSQL choices",
        config={"databases": {"default": {"provider": "memory"}}},
    )
    domain.register(aggregate_cls)
    domain.init(traverse=False)
    provider = MssqlProvider(
        name="mssql",
        domain=domain,
        conn_info={"provider": "mssql", "database_uri": MSSQL_URI},
    )
    with domain.domain_context():
        return provider.construct_database_model_class(aggregate_cls).__table__


def test_a_unique_string_with_choices_keeps_its_length():
    class UniqueStatus(BaseAggregate):
        status: String(max_length=20, choices=["draft", "published"], unique=True)

    column = build_table(UniqueStatus).c["status"]

    assert column.type.length == 20
    assert column.unique is True


def test_a_unique_string_with_choices_and_no_max_length_is_rejected():
    class UnboundedStatus(BaseAggregate):
        status: String(max_length=None, choices=["draft", "published"], unique=True)

    with pytest.raises(IncorrectUsageError) as exc:
        build_table(UnboundedStatus)

    assert "status" in str(exc.value)
