"""Date and time column types for the SQL Server provider.

Nothing here opens a connection. A provider constructed on its own skips the
liveness check, so the core suite can pin the column types the adapter picks
when it builds a model. The round-trip against a live SQL Server lives in
``mssql/``.

SQL Server's ``DATETIME`` rounds to increments of about 3 ms, so two timestamps
written microseconds apart can read back equal without any error.
"""

import types

import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import mssql as mssql_dialect
from sqlalchemy.dialects import mysql as mysql_dialect
from sqlalchemy.schema import CreateTable

from protean import Domain
from protean.adapters.repository.sqlalchemy import (
    MSSQLJSON,
    MssqlProvider,
    MysqlProvider,
    PostgresqlProvider,
    SqliteProvider,
)
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import Date, DateTime, Dict, String, ValueObject
from protean.utils.consume_idempotency import ProcessedMessage
from protean.utils.outbox import Outbox
from tests.shared import MSSQL_URI, MYSQL_URI, POSTGRES_URI

pytestmark = pytest.mark.no_test_domain


class Booking(BaseAggregate):
    reference: String(max_length=50)
    booked_at: DateTime(required=True)
    cancelled_at: DateTime()
    travel_date: Date()
    extra: Dict()


class Window(BaseValueObject):
    opens_at: DateTime()
    opens_on: Date()


class Slot(BaseAggregate):
    window: ValueObject(Window)


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


def stub_dbapi():
    """A DBAPI module that stands in for pyodbc.

    pyodbc loads only where the unixODBC library is installed, and nothing here
    connects, so the SQL Server engine gets this module instead.
    """
    dbapi = types.ModuleType("stub_dbapi")
    dbapi.paramstyle = "qmark"
    dbapi.version = "5.0.0"
    dbapi.Cursor = type("Cursor", (), {"nextset": None})
    return dbapi


def table_for(aggregate_cls, provider_cls=MssqlProvider, uri=MSSQL_URI):
    """The SQLAlchemy ``Table`` ``provider_cls`` builds for ``aggregate_cls``."""
    domain = host_domain(aggregate_cls)
    conn_info = {"provider": provider_cls.__database__, "database_uri": uri}
    if provider_cls is MssqlProvider:
        conn_info["module"] = stub_dbapi()
    provider = provider_cls(name="sql", domain=domain, conn_info=conn_info)
    with domain.domain_context():
        return provider.construct_database_model_class(aggregate_cls).__table__


def sql_server_2016():
    """The SQL Server dialect as it is set up after connecting to a 2016 server.

    A bare ``mssql.dialect()`` assumes a server older than 2008 and compiles
    ``Date`` as ``DATETIME``.
    """
    dialect = mssql_dialect.dialect()
    dialect.server_version_info = (13,)
    dialect._setup_version_attributes()
    return dialect


def column_ddl(table, name):
    """The line ``CREATE TABLE`` emits on SQL Server for column ``name``."""
    ddl = str(CreateTable(table).compile(dialect=sql_server_2016()))
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

    def test_date_is_not_widened(self):
        table = table_for(Booking)

        assert not isinstance(table.c["travel_date"].type, sa_types.DateTime)
        assert column_ddl(table, "travel_date") == "travel_date DATE NULL"

    def test_other_types_are_left_alone(self):
        table = table_for(Booking)

        assert column_ddl(table, "reference") == "reference VARCHAR(50) NULL"
        assert isinstance(table.c["extra"].type, MSSQLJSON)

    def test_a_value_object_datetime_is_a_datetime2(self):
        table = table_for(Slot)

        assert column_ddl(table, "window_opens_at") == "window_opens_at DATETIME2 NULL"
        assert column_ddl(table, "window_opens_on") == "window_opens_on DATE NULL"

    def test_the_processed_message_timestamp_is_a_datetime2(self):
        table = table_for(ProcessedMessage)

        assert column_ddl(table, "processed_at") == "processed_at DATETIME2 NULL"

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
