"""Date and time column types for the SQL Server provider.

Nothing here opens a connection. A provider constructed on its own (rather than
through ``domain.init()``) skips the liveness check, so the column types the
adapter picks at model-construction time are pinned in the core suite. The
round-trip against a live SQL Server lives in ``mssql/``.

SQL Server's ``DATETIME`` rounds to increments of about 3 ms, so two timestamps
written microseconds apart can read back equal. Nothing fails when that happens,
which is why the column type is asserted directly.
"""

import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import mssql as mssql_dialect
from sqlalchemy.dialects import mysql as mysql_dialect
from sqlalchemy.schema import CreateTable

from protean import Domain
from protean.adapters.repository.sqlalchemy import (
    MssqlProvider,
    MysqlProvider,
    PostgresqlProvider,
    SqliteProvider,
)
from protean.core.aggregate import BaseAggregate
from protean.fields import Date, DateTime, Dict, String
from protean.utils.outbox import Outbox
from tests.shared import MSSQL_URI, MYSQL_URI, POSTGRES_URI

pytestmark = pytest.mark.no_test_domain


class Booking(BaseAggregate):
    reference: String(max_length=50)
    booked_at: DateTime(required=True)
    cancelled_at: DateTime()
    travel_date: Date()
    extra: Dict()


def host_domain(aggregate_cls):
    """A memory-backed domain that owns ``aggregate_cls``.

    The SQL providers are built separately against it, so nothing in this
    module needs a running server.
    """
    domain = Domain(
        name="MSSQL mapping",
        config={
            "identity_type": "uuid",
            "databases": {"default": {"provider": "memory"}},
        },
    )
    domain.register(aggregate_cls)
    domain.init(traverse=False)
    return domain


def table_for(aggregate_cls, provider_cls=MssqlProvider, uri=MSSQL_URI):
    """The SQLAlchemy ``Table`` ``provider_cls`` builds for ``aggregate_cls``."""
    domain = host_domain(aggregate_cls)
    provider = provider_cls(
        name="sql",
        domain=domain,
        conn_info={"provider": provider_cls.__database__, "database_uri": uri},
    )
    with domain.domain_context():
        return provider.construct_database_model_class(aggregate_cls).__table__


def column_ddl(table, name):
    """The line ``CREATE TABLE`` emits on SQL Server for column ``name``."""
    ddl = str(CreateTable(table).compile(dialect=mssql_dialect.dialect()))
    lines = [line.strip().rstrip(",") for line in ddl.splitlines()]
    matching = [line for line in lines if line.startswith(f"{name} ")]
    assert len(matching) == 1, ddl
    return matching[0]


class TestDateTimeOnSqlServer:
    def test_datetime_is_a_datetime2(self):
        table = table_for(Booking)

        assert isinstance(table.c["booked_at"].type, mssql_dialect.DATETIME2)
        assert column_ddl(table, "booked_at") == "booked_at DATETIME2 NOT NULL"

    def test_an_optional_datetime_stays_nullable(self):
        table = table_for(Booking)

        assert isinstance(table.c["cancelled_at"].type, mssql_dialect.DATETIME2)
        assert column_ddl(table, "cancelled_at") == "cancelled_at DATETIME2 NULL"

    def test_precision_is_left_at_the_server_default(self):
        """``DATETIME2`` with no precision is ``DATETIME2(7)``, 100 ns steps."""
        column = table_for(Booking).c["booked_at"]

        assert column.type.precision is None

    def test_date_is_not_widened(self):
        column = table_for(Booking).c["travel_date"]

        assert isinstance(column.type, sa_types.Date)
        assert not isinstance(column.type, sa_types.DateTime)

    def test_other_types_are_left_alone(self):
        table = table_for(Booking)

        assert column_ddl(table, "reference") == "reference VARCHAR(50) NULL"
        assert not isinstance(table.c["extra"].type, mssql_dialect.DATETIME2)

    def test_every_outbox_timestamp_is_a_datetime2(self):
        """The claim orders on ``created_at``, so rounding it reorders rows."""
        table = table_for(Outbox)
        timestamps = [
            "created_at",
            "published_at",
            "last_processed_at",
            "next_retry_at",
            "locked_until",
        ]

        for name in timestamps:
            assert isinstance(table.c[name].type, mssql_dialect.DATETIME2), name
        assert column_ddl(table, "created_at") == "created_at DATETIME2 NULL"


class TestDateTimeOnOtherDatabases:
    """The ``DATETIME2`` swap is gated on the SQL Server dialect."""

    def test_postgresql_keeps_timestamp(self):
        column = table_for(Booking, PostgresqlProvider, POSTGRES_URI).c["booked_at"]

        assert type(column.type) is sa_types.DateTime

    def test_sqlite_keeps_datetime(self):
        column = table_for(Booking, SqliteProvider, "sqlite:///:memory:").c["booked_at"]

        assert type(column.type) is sa_types.DateTime

    def test_mysql_keeps_datetime_with_microseconds(self):
        column = table_for(Booking, MysqlProvider, MYSQL_URI).c["booked_at"]

        assert isinstance(column.type, mysql_dialect.DATETIME)
        assert column.type.fsp == 6
