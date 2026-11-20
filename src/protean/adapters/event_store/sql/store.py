"""The SQL event store on its own SQLite file or PostgreSQL database.

PostgreSQL lock key
-------------------
A write to category ``<category>`` in schema ``<schema>`` takes
``pg_advisory_xact_lock(<key>)``, where ``<key>`` is Message DB's ``hash_64``
of ``"<schema>.messages:<category>"``: the first 16 hex digits of the text's
MD5 digest, read as a signed 64-bit integer. The key format is a stable
contract. During a rolling deploy, writers of two Protean versions run at
once, and their writes to one category wait for each other only when both
compute the same key.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

try:
    from sqlalchemy import (
        Connection,
        Engine,
        MetaData,
        Row,
        Select,
        create_engine,
        event,
        func,
        select,
        text,
    )
    from sqlalchemy.dialects.postgresql import insert as postgresql_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.engine.url import URL, make_url
    from sqlalchemy.exc import ArgumentError, IntegrityError
except ImportError as exc:
    raise ImportError(
        "The SQL event store needs SQLAlchemy. Install the `sqlite` or "
        '`postgresql` extra: `pip install "protean[sqlite]"` or '
        '`pip install "protean[postgresql]"`.'
    ) from exc

from protean.adapters.database.sqlalchemy import (
    POSTGRESQL_ENGINE_DEFAULTS,
    _custom_json_dumps,
    queue_pool_stats,
    resolve_postgresql_url,
)
from protean.adapters.event_store.sql.schema import (
    STREAM_POSITION_CONSTRAINT,
    build_tables,
)
from protean.exceptions import (
    ConfigurationError,
    ExpectedVersionError,
    NotSupportedError,
)
from protean.port.event_store import (
    EventStoreCapabilities,
    EventStoreHealth,
    EventStorePort,
    RawMessage,
)
from protean.utils.globals import _domain_now

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

_BACKENDS = ("sqlite", "postgresql")

# Config keys that describe the store rather than the SQLAlchemy engine. Every
# other key goes to ``create_engine``, as on the SQLAlchemy database provider.
_NON_ENGINE_KEYS = frozenset({"provider", "database_uri", "schema"})

# The isolation levels each database accepts. The PostgreSQL engine runs READ
# COMMITTED unless the config names READ UNCOMMITTED, which PostgreSQL runs as
# READ COMMITTED.
_SAFE_ISOLATION_LEVELS: dict[str, frozenset[str]] = {
    "postgresql": frozenset({"READ COMMITTED", "READ UNCOMMITTED"}),
    "sqlite": frozenset({"SERIALIZABLE", "READ UNCOMMITTED"}),
}

# The isolation levels each database refuses with a reason. Under the two
# stricter PostgreSQL levels the transaction's snapshot is taken by the lock
# statement before the lock is granted, so the version check would read stale
# data. On SQLite, ``BEGIN IMMEDIATE`` takes the write lock before any read, so
# only ``AUTOCOMMIT``, which runs no transaction, is unsafe.
_AUTOCOMMIT_REASON = (
    "it runs each statement in its own transaction, so the version check and "
    "the insert do not commit together"
)
_STALE_SNAPSHOT_REASON = (
    "the transaction's snapshot is taken before the category lock is granted, "
    "so the version check would read stale data"
)
_UNSAFE_ISOLATION_LEVELS: dict[str, dict[str, str]] = {
    "postgresql": {
        "AUTOCOMMIT": _AUTOCOMMIT_REASON,
        "REPEATABLE READ": _STALE_SNAPSHOT_REASON,
        "SERIALIZABLE": _STALE_SNAPSHOT_REASON,
    },
    "sqlite": {"AUTOCOMMIT": _AUTOCOMMIT_REASON},
}

# A stream name that holds this text is a snapshot stream.
_SNAPSHOT_MARKER = ":snapshot-"

# The execution option that makes a SQLite transaction start with
# ``BEGIN IMMEDIATE``. Only writes set it.
_BEGIN_IMMEDIATE = "sqlite_begin_immediate"

# The text SQLite gives a violation of ``uq_messages_stream_position``.
_SQLITE_STREAM_POSITION_VIOLATION = (
    "UNIQUE constraint failed: messages.stream_name, messages.position"
)


def _lock_key(schema: str, category: str) -> int:
    """Return the PostgreSQL advisory lock key of ``category`` in ``schema``.

    See the module docstring for the format.
    """
    digest = hashlib.md5(
        f"{schema}.messages:{category}".encode(), usedforsecurity=False
    ).hexdigest()
    key = int(digest[:16], 16)
    return key - 2**64 if key >= 2**63 else key


def _category(stream_name: str) -> str:
    # Message DB's ``category(stream_name)``: the text before the first ``-``.
    return stream_name.partition("-")[0]


def _store_url(name: str, config: Mapping[str, Any]) -> URL:
    """Return the parsed ``database_uri``.

    Raises:
        ConfigurationError: When ``database_uri`` is missing or unparseable,
            names a database other than SQLite or PostgreSQL, or is an
            in-memory SQLite database.
    """
    uri = config.get("database_uri")
    if not uri:
        raise ConfigurationError(
            f"Event store '{name}' uses provider 'sql' without a database_uri. "
            "Set database_uri under [event_store] to a sqlite:/// file URL or "
            "a postgresql:// URL."
        )
    try:
        url = make_url(uri)
    # make_url raises ArgumentError for a malformed URI and ValueError for a
    # port that is not a number.
    except (ArgumentError, ValueError) as exc:
        raise ConfigurationError(
            f"Event store '{name}' has a database_uri that cannot be parsed: {exc}"
        ) from exc

    backend = url.get_backend_name()
    if backend not in _BACKENDS:
        raise ConfigurationError(
            f"Event store '{name}' has a '{url.drivername}://' database_uri. "
            f"The sql event store supports {' and '.join(_BACKENDS)}."
        )
    if backend == "sqlite" and _is_in_memory(url):
        raise ConfigurationError(
            f"Event store '{name}' has an in-memory SQLite database_uri. The sql "
            "event store needs a SQLite file, such as sqlite:///events.db. Use "
            "the memory event store for an event store in process memory."
        )
    return url


def _is_in_memory(url: URL) -> bool:
    database = url.database or ""
    return (
        database in ("", ":memory:")
        or database.startswith("file::memory:")
        or url.query.get("mode") == "memory"
    )


def _schema(name: str, backend: str, config: Mapping[str, Any]) -> str | None:
    """Return the store's schema: ``schema``, or ``public`` on PostgreSQL.

    Raises:
        ConfigurationError: When ``schema`` is set on SQLite, or is not a
            non-empty string on PostgreSQL.
    """
    if backend == "sqlite":
        if "schema" in config:
            raise ConfigurationError(
                f"Event store '{name}' sets schema on SQLite, which has no "
                "schemas. Remove the schema key."
            )
        return None
    if "schema" not in config:
        return "public"
    schema = config["schema"]
    if not isinstance(schema, str) or not schema.strip():
        raise ConfigurationError(
            f"Event store '{name}' has schema {schema!r}. Set schema to the "
            "name of a PostgreSQL schema, or remove it to use public."
        )
    return schema


def _check_isolation_level(name: str, backend: str, config: Mapping[str, Any]) -> None:
    """Raise ``ConfigurationError`` unless the config's isolation level is safe.

    The level is read from ``isolation_level`` and from
    ``execution_options.isolation_level``. ``execution_options`` must be a
    table.
    """
    execution_options = config.get("execution_options", {})
    if not isinstance(execution_options, Mapping):
        raise ConfigurationError(
            f"Event store '{name}' has execution_options "
            f"{execution_options!r}. Set execution_options to a table."
        )
    levels = [config.get("isolation_level"), execution_options.get("isolation_level")]
    for level in levels:
        if level is None:
            continue
        normalized = str(level).upper().replace("_", " ")
        if normalized in _SAFE_ISOLATION_LEVELS[backend]:
            continue
        reason = _UNSAFE_ISOLATION_LEVELS[backend].get(
            normalized, f"{backend} does not run this level"
        )
        raise ConfigurationError(
            f"Event store '{name}' sets isolation level {level!r} on "
            f"{backend}, which the sql event store refuses: {reason}."
        )


def _engine_args(backend: str, config: Mapping[str, Any]) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if backend == "postgresql":
        args.update(POSTGRESQL_ENGINE_DEFAULTS)
        # Set on the engine, the level is applied to every new connection, so
        # a server, role or connect_args default can never change it.
        args["isolation_level"] = "READ COMMITTED"
    args.update(
        (key, value) for key, value in config.items() if key not in _NON_ENGINE_KEYS
    )
    return args


def _install_sqlite_settings(engine: Engine) -> None:
    """Set WAL and the busy timeout, and start writes with ``BEGIN IMMEDIATE``.

    SQLAlchemy's documented recipe for pysqlite: the driver's own transaction
    handling is turned off on connect, and the ``begin`` event emits the
    ``BEGIN``. A transaction on a connection with the ``_BEGIN_IMMEDIATE``
    execution option takes the write lock at its start. Any other transaction
    starts with a plain ``BEGIN``, so under WAL a read runs while another
    connection writes.
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA busy_timeout = 5000")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Connection) -> None:
        if conn.get_execution_options().get(_BEGIN_IMMEDIATE):
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("BEGIN")


def _is_stream_position_violation(exc: IntegrityError) -> bool:
    # psycopg 3 and psycopg2 both name the constraint on ``diag``.
    diag = getattr(exc.orig, "diag", None)
    if getattr(diag, "constraint_name", None) == STREAM_POSITION_CONSTRAINT:
        return True
    return _SQLITE_STREAM_POSITION_VIOLATION in str(exc.orig)


def _check_expected_version(
    stream_name: str, expected_version: int | None, stream_version: int
) -> None:
    """Raise ``ExpectedVersionError`` unless ``expected_version`` matches.

    ``stream_version`` is the stream's last position, or -1 when it is empty.
    """
    if expected_version is not None and expected_version != stream_version:
        raise ExpectedVersionError(
            f"Wrong expected version: {expected_version} "
            f"(Stream: {stream_name}, Stream Version: {stream_version})"
        )


def _check_limit(limit: int) -> None:
    # SQLite reads a negative LIMIT as no limit and PostgreSQL refuses it, so
    # the store refuses it on both.
    if limit < 0:
        raise ValueError(f"limit must be 0 or more, not {limit}")


def _now() -> datetime:
    # The domain clock can return an aware time in any zone. SQLite drops the
    # zone when it stores a time, so every write stores UTC.
    return _domain_now().astimezone(UTC)


def _utc(time: datetime) -> datetime:
    # SQLite stores the time without its zone, and the store writes UTC.
    # PostgreSQL returns the session's zone, which may not be UTC.
    if time.tzinfo is None:
        return time.replace(tzinfo=UTC)
    return time.astimezone(UTC)


def _raw_message(row: Row[Any], global_position: int | None = None) -> RawMessage:
    """Return ``row`` as a ``RawMessage``.

    ``global_position`` overrides the row's own, for a snapshot row that has none.
    """
    return RawMessage(
        id=row.id,
        stream_name=row.stream_name,
        type=row.type,
        position=int(row.position),
        global_position=(
            int(row.global_position) if global_position is None else global_position
        ),
        data=row.data,
        metadata=row.metadata,
        time=_utc(row.time),
    )


class SqlEventStore(EventStorePort):
    """An event store on a SQLite file or a PostgreSQL database.

    ``database_uri`` selects the database by its scheme, ``sqlite`` or
    ``postgresql``. Events live in ``messages`` and snapshots in ``snapshots``.
    Each write commits on its own connection, as on Message DB.

    A write takes the category lock, reads the stream's last position, checks
    the expected version and inserts, in one transaction. On PostgreSQL the
    lock is ``pg_advisory_xact_lock`` with the key the module docstring
    defines. On SQLite the write lock ``BEGIN IMMEDIATE`` takes is the lock.

    Raises:
        ConfigurationError: At construction, when ``database_uri`` is missing,
            names a database other than SQLite or PostgreSQL, or is an
            in-memory SQLite database; when ``schema`` is set on SQLite; when
            the isolation level is unsafe for the database; or when the
            PostgreSQL driver cannot be imported.
        ValueError: On a read with a negative ``limit``.
    """

    def __init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = config

        url = _store_url(name, config)
        self._backend = url.get_backend_name()
        self._schema = _schema(name, self._backend, config)
        _check_isolation_level(name, self._backend, config)
        if self._backend == "postgresql":
            url = resolve_postgresql_url(url, name, kind="Event store")

        self._engine = create_engine(
            url,
            json_serializer=_custom_json_dumps,
            **_engine_args(self._backend, config),
        )
        if self._backend == "sqlite":
            _install_sqlite_settings(self._engine)
        # Writes go through this engine. It shares the pool and listeners of
        # ``_engine``; on SQLite its transactions start with BEGIN IMMEDIATE.
        self._write_engine = self._engine.execution_options(**{_BEGIN_IMMEDIATE: True})

        self._metadata = MetaData(schema=self._schema)
        self._messages, self._snapshots = build_tables(self._metadata)

    @property
    def capabilities(self) -> EventStoreCapabilities:
        # No CONSUMER_GROUPS: a category read with a consumer-group argument
        # raises NotSupportedError (ADR-0048, decision 12).
        return (
            EventStoreCapabilities.PRODUCTION | EventStoreCapabilities.SCHEMA_MANAGEMENT
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        if _SNAPSHOT_MARKER in stream_name:
            return self._write_snapshot(stream_name, message_type, data, metadata)
        try:
            with self._write_engine.begin() as conn:
                return self._append(
                    conn, stream_name, message_type, data, metadata, expected_version
                )
        except IntegrityError as exc:
            # The version check runs under the category lock, so this is a
            # writer that bypassed the lock. Any other violation, such as a
            # duplicate ``id``, propagates.
            if not _is_stream_position_violation(exc):
                raise
            raise ExpectedVersionError(
                f"Wrong expected version: {expected_version} "
                f"(Stream: {stream_name}): another writer appended at the same "
                "position"
            ) from exc

    def _append(
        self,
        conn: Connection,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None,
        expected_version: int | None,
    ) -> int:
        category = _category(stream_name)
        if self._backend == "postgresql":
            key = _lock_key(self._schema or "public", category)
            conn.execute(select(func.pg_advisory_xact_lock(key)))
        self._on_lock_taken()

        stream_version = self._last_position(conn, stream_name)
        _check_expected_version(stream_name, expected_version, stream_version)

        position = stream_version + 1
        conn.execute(
            self._messages.insert().values(
                id=str(uuid4()),
                stream_name=stream_name,
                category=category,
                position=position,
                type=message_type,
                data=dict(data),
                metadata=dict(metadata) if metadata is not None else None,
                time=_now(),
            )
        )
        return position

    def _on_lock_taken(self) -> None:
        """Run after the category lock is taken. Tests patch it; it does nothing."""

    def _last_position(self, conn: Connection, stream_name: str) -> int:
        """Return the stream's last position, or -1 when it is empty."""
        last = conn.execute(
            select(func.max(self._messages.c.position)).where(
                self._messages.c.stream_name == stream_name
            )
        ).scalar_one()
        return -1 if last is None else int(last)

    def _write_snapshot(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None,
    ) -> int:
        """Upsert the snapshot stream's one row and return its position.

        The position counts the writes to the stream from 0. No category lock
        is taken: ``ON CONFLICT`` makes two first writes safe. The row's
        ``metadata`` is always NULL, whatever the caller passes.
        """
        table = self._snapshots
        insert = postgresql_insert if self._backend == "postgresql" else sqlite_insert
        values = {
            "id": str(uuid4()),
            "type": message_type,
            "data": dict(data),
            "metadata": None,
            "time": _now(),
        }
        statement = insert(table).values(stream_name=stream_name, position=0, **values)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.stream_name],
            set_={"position": table.c.position + 1, **values},
        )
        with self._write_engine.begin() as conn:
            conn.execute(statement)
            position: int = conn.execute(
                select(table.c.position).where(table.c.stream_name == stream_name)
            ).scalar_one()
        return position

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        _check_limit(limit)
        if _SNAPSHOT_MARKER in stream_name:
            snapshot = self._snapshot(stream_name)
            if snapshot is None or snapshot["position"] < position or limit < 1:
                return []
            return [snapshot]
        messages = self._messages
        return self._fetch(
            self._select_messages()
            .where(messages.c.stream_name == stream_name)
            .where(messages.c.position >= position)
            .order_by(messages.c.position)
            .limit(limit)
        )

    def get_category_messages(
        self,
        category: str,
        position: int = 0,
        limit: int = 1000,
        *,
        consumer_group_member: int | None = None,
        consumer_group_size: int | None = None,
    ) -> list[RawMessage]:
        if consumer_group_member is not None or consumer_group_size is not None:
            raise NotSupportedError(
                "The sql event store does not support consumer groups"
            )
        _check_limit(limit)
        messages = self._messages
        # ``category`` is filled at insert, so this is an exact match: a read
        # of ``user`` returns no ``users`` streams. Snapshots live in their own
        # table, so no category read returns one.
        return self._fetch(
            self._select_messages()
            .where(messages.c.category == category)
            .where(messages.c.global_position >= position)
            .order_by(messages.c.global_position)
            .limit(limit)
        )

    def get_all_messages(
        self, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        _check_limit(limit)
        messages = self._messages
        return self._fetch(
            self._select_messages()
            .where(messages.c.global_position >= position)
            .order_by(messages.c.global_position)
            .limit(limit)
        )

    def get_last_stream_message(self, stream_name: str) -> RawMessage | None:
        if _SNAPSHOT_MARKER in stream_name:
            return self._snapshot(stream_name)
        messages = self._messages
        return self._first(
            self._select_messages()
            .where(messages.c.stream_name == stream_name)
            .order_by(messages.c.position.desc())
        )

    def get_last_category_message(self, category: str) -> RawMessage | None:
        messages = self._messages
        return self._first(
            self._select_messages()
            .where(messages.c.category == category)
            .order_by(messages.c.global_position.desc())
        )

    def get_last_message(self) -> RawMessage | None:
        return self._first(
            self._select_messages().order_by(self._messages.c.global_position.desc())
        )

    def stream_ids(self, category: str) -> list[str]:
        messages = self._messages
        with self._engine.connect() as conn:
            names = conn.execute(
                select(messages.c.stream_name)
                .where(messages.c.category == category)
                .distinct()
            ).scalars()
            identifiers = {name.partition("-")[2] for name in names}
        identifiers.discard("")
        return sorted(identifiers)

    def _select_messages(self) -> Select[Any]:
        messages = self._messages
        return select(
            messages.c.id,
            messages.c.stream_name,
            messages.c.type,
            messages.c.position,
            messages.c.global_position,
            messages.c.data,
            messages.c.metadata,
            messages.c.time,
        )

    def _fetch(self, statement: Select[Any]) -> list[RawMessage]:
        with self._engine.connect() as conn:
            return [_raw_message(row) for row in conn.execute(statement)]

    def _first(self, statement: Select[Any]) -> RawMessage | None:
        rows = self._fetch(statement.limit(1))
        return rows[0] if rows else None

    def _snapshot(self, stream_name: str) -> RawMessage | None:
        """Return the snapshot stream's row, with ``global_position`` 0."""
        table = self._snapshots
        with self._engine.connect() as conn:
            row = conn.execute(
                select(table).where(table.c.stream_name == stream_name)
            ).one_or_none()
        # A snapshot holds no place in the store's order, so its
        # ``global_position`` is 0, below the first event's 1.
        return None if row is None else _raw_message(row, global_position=0)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Run ``SELECT 1``. Never raises."""
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # an unreachable database reports False; logged
            # Health checks call this on every poll, so an outage logs at
            # debug instead of a warning per poll.
            logger.debug("SQL event store ping failed", exc_info=True)
            return False
        return True

    def health(self) -> EventStoreHealth:
        return EventStoreHealth(
            reachable=self.ping(), pool=queue_pool_stats(self._engine)
        )

    def get_connection(self) -> Engine:
        """Return the store's SQLAlchemy engine."""
        return self._engine

    def create_schema(self) -> None:
        """Create the ``messages`` and ``snapshots`` tables that do not exist."""
        self._metadata.create_all(self._engine, checkfirst=True)

    def drop_schema(self) -> None:
        """Drop the ``messages`` and ``snapshots`` tables that exist."""
        self._metadata.drop_all(self._engine, checkfirst=True)

    def clear(self) -> None:
        """Delete every row and restart the global position at 1. Test use only."""
        with self._write_engine.begin() as conn:
            if self._backend == "postgresql":
                preparer = self._engine.dialect.identifier_preparer
                tables = ", ".join(
                    preparer.format_table(t) for t in (self._messages, self._snapshots)
                )
                conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY"))
                return
            conn.execute(self._messages.delete())
            conn.execute(self._snapshots.delete())
            conn.execute(text("DELETE FROM sqlite_sequence WHERE name = 'messages'"))

    def close(self) -> None:
        """Dispose of the engine's pooled connections."""
        self._engine.dispose()


_PORT_CHECK: type[EventStorePort] = SqlEventStore
