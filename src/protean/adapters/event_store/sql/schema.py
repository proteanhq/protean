"""The two tables of the SQL event store: ``messages`` and ``snapshots``."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

# ``JSONB`` on PostgreSQL, ``JSON`` elsewhere. A Python ``None`` is stored as SQL
# ``NULL``, not the JSON value ``null``.
_JSON = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")

# SQLite gives a row id only to an ``INTEGER`` primary key, so the column is
# ``BIGINT`` on PostgreSQL and ``INTEGER`` on SQLite.
_GLOBAL_POSITION = BigInteger().with_variant(Integer(), "sqlite")

# The name of the unique constraint a stale write breaks. The store maps a
# violation of it, and only it, to ``ExpectedVersionError``.
STREAM_POSITION_CONSTRAINT = "uq_messages_stream_position"


def build_tables(metadata: MetaData) -> tuple[Table, Table]:
    """Add the ``messages`` and ``snapshots`` tables to ``metadata``.

    Returns the two tables in that order. The tables take the schema of
    ``metadata``.

    ``messages`` holds Message DB's columns plus ``category``, the stream name
    up to its first ``-``. ``global_position`` starts at 1 and is an identity
    column on PostgreSQL and an ``AUTOINCREMENT`` row id on SQLite.
    ``snapshots`` holds one row per snapshot stream and takes no global
    position.
    """
    messages = Table(
        "messages",
        metadata,
        Column(
            "global_position",
            _GLOBAL_POSITION,
            Identity(start=1),
            primary_key=True,
        ),
        Column("id", Text, nullable=False),
        Column("stream_name", Text, nullable=False),
        Column("category", Text, nullable=False),
        Column("position", BigInteger, nullable=False),
        Column("type", Text, nullable=False),
        Column("data", _JSON),
        Column("metadata", _JSON),
        Column("time", DateTime(timezone=True), nullable=False),
        UniqueConstraint("stream_name", "position", name=STREAM_POSITION_CONSTRAINT),
        UniqueConstraint("id", name="uq_messages_id"),
        Index("ix_messages_category_global_position", "category", "global_position"),
        sqlite_autoincrement=True,
    )
    snapshots = Table(
        "snapshots",
        metadata,
        Column("stream_name", Text, primary_key=True),
        Column("id", Text, nullable=False),
        Column("type", Text, nullable=False),
        Column("position", BigInteger, nullable=False),
        Column("data", _JSON),
        Column("metadata", _JSON),
        Column("time", DateTime(timezone=True), nullable=False),
    )
    return messages, snapshots
