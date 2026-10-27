"""``DateTime`` fields keep microseconds on SQL Server.

SQL Server's ``DATETIME`` rounds to increments of about 3 ms. The provider maps
``DateTime`` to ``DATETIME2``, so two values 100 microseconds apart read back
exactly as written.
"""

from datetime import datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import mssql as mssql_dialect

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime
from tests.shared import initialize_domain

from .elements import MssqlTimestampedEntity


class MssqlLegacyTimestampedEntity(BaseAggregate):
    occurred_at: DateTime()


def column_type(provider, table, name):
    columns = inspect(provider._engine).get_columns(table, schema="dbo")
    matching = [c for c in columns if c["name"] == name]
    assert len(matching) == 1
    return matching[0]["type"]


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(MssqlTimestampedEntity)
    test_domain.init(traverse=False)


@pytest.mark.mssql
class TestDateTimePrecision:
    def test_the_created_column_is_datetime2(self, test_domain):
        provider = test_domain.providers["default"]
        occurred_at = column_type(provider, "mssql_timestamped_entity", "occurred_at")

        assert isinstance(occurred_at, mssql_dialect.DATETIME2)

    def test_an_existing_datetime_column_is_left_alone(self):
        """``create_all`` skips a table that exists, so its type is kept."""
        domain = initialize_domain(name="MSSQL existing table", root_path=__file__)
        domain.register(MssqlLegacyTimestampedEntity)
        domain.init(traverse=False)
        provider = domain.providers["default"]
        table = "mssql_legacy_timestamped_entity"
        with provider._engine.begin() as conn:
            conn.execute(
                text(
                    f"CREATE TABLE dbo.{table} "
                    "(id VARCHAR(36) PRIMARY KEY, occurred_at DATETIME NULL)"
                )
            )
        try:
            with domain.domain_context():
                provider._create_database_artifacts()

            occurred_at = column_type(provider, table, "occurred_at")
            assert isinstance(occurred_at, mssql_dialect.DATETIME)
            assert not isinstance(occurred_at, mssql_dialect.DATETIME2)
        finally:
            with provider._engine.begin() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS dbo.{table}"))
            provider.close()

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
