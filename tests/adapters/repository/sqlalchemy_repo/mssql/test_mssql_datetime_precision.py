"""``DateTime`` fields keep microseconds on SQL Server.

SQL Server's ``DATETIME`` rounds to increments of about 3 ms. The provider maps
``DateTime`` to ``DATETIME2``, so two values 100 microseconds apart read back
exactly as written.
"""

from datetime import datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import mssql as mssql_dialect

from .elements import MssqlTimestampedEntity


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(MssqlTimestampedEntity)
    test_domain.init(traverse=False)


@pytest.mark.mssql
class TestDateTimePrecision:
    def test_the_created_column_is_datetime2(self, test_domain):
        provider = test_domain.providers["default"]
        columns = inspect(provider._engine).get_columns(
            "mssql_timestamped_entity", schema="dbo"
        )
        occurred_at = [c for c in columns if c["name"] == "occurred_at"]

        assert len(occurred_at) == 1
        assert isinstance(occurred_at[0]["type"], mssql_dialect.DATETIME2)

    def test_values_100_microseconds_apart_round_trip(self, test_domain):
        earlier = datetime(2026, 10, 26, 12, 0, 0, 123400)
        later = datetime(2026, 10, 26, 12, 0, 0, 123500)
        repo = test_domain.repository_for(MssqlTimestampedEntity)
        first = MssqlTimestampedEntity(label="earlier", occurred_at=earlier)
        second = MssqlTimestampedEntity(label="later", occurred_at=later)
        repo.add(first)
        repo.add(second)

        read_first = repo.get(first.id).occurred_at
        read_second = repo.get(second.id).occurred_at

        assert read_first == earlier
        assert read_second == later
        assert read_first != read_second
