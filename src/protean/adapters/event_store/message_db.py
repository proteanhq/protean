from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qsl, urlparse

import psycopg2
from message_db.client import MessageDB
from message_db.connection import ConnectionPool

from protean.exceptions import ConfigurationError, ExpectedVersionError
from protean.port.event_store import (
    BaseEventStore,
    EventStoreCapabilities,
    EventStoreHealth,
    EventStorePort,
    RawMessage,
)
from protean.port.health import PoolStats

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


def _superuser_connection(database_uri: str) -> psycopg2.extensions.connection:
    """Open a ``psycopg2`` connection to ``database_uri`` as ``postgres``.

    Test-harness use only. Works only against the Postgres instance in the
    configured Docker container: it connects as the ``postgres`` superuser, which
    is assumed to have no password. Neither holds in production, so this must
    never run there. Any change to the connection convention has to be made
    here, the single place every superuser connection to the store goes through.
    The caller closes the connection.
    """
    parsed = urlparse(database_uri)
    # ``parse_qsl`` tolerates odd query strings (a trailing ``&``, an empty
    # segment, a segment with no ``=``) that a hand-rolled ``split`` would choke
    # on, so a slightly different ``database_uri`` cannot break the connection.
    query_params = dict(parse_qsl(parsed.query))
    return psycopg2.connect(
        dbname=parsed.path[1:],
        user="postgres",
        port=parsed.port,
        host=parsed.hostname,
        sslmode=query_params.get("sslmode", "disable"),
    )


def _truncate_message_store(database_uri: str) -> None:
    """Empty the Message-DB store at ``database_uri``. Test-harness use only.

    Connects through :func:`_superuser_connection`; see its docstring for the
    Docker-only connection convention.
    """
    conn = _superuser_connection(database_uri)
    try:
        cursor = conn.cursor()
        cursor.execute("TRUNCATE message_store.messages RESTART IDENTITY;")
        conn.commit()  # psycopg2 requires a commit even for a TRUNCATE
        cursor.close()
    finally:
        conn.close()


class MessageDBStore(BaseEventStore):
    """MessageDB event store adapter.

    Connection pool parameters can be configured via config:
        - max_connections: Maximum number of connections in the pool
    """

    # Keys from config that are forwarded to MessageDB connection pool
    _POOL_KEYS = frozenset({"max_connections"})

    def __init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None:
        super().__init__(name, domain, config)

        self._client: MessageDB | None = None
        self._pool_kwargs: dict[str, Any] = {
            key: value for key, value in config.items() if key in self._POOL_KEYS
        }

    @property
    def capabilities(self) -> EventStoreCapabilities:
        # CONSUMER_GROUPS: ``get_category_messages`` passes the group member and
        # size to Message DB's ``get_category_messages`` function. No
        # SCHEMA_MANAGEMENT: Message DB's own scripts install the schema.
        return (
            EventStoreCapabilities.PRODUCTION | EventStoreCapabilities.CONSUMER_GROUPS
        )

    def get_connection(self) -> MessageDB:
        """Return the MessageDB client, creating it on first use.

        Raises:
            ConfigurationError: When the client cannot connect to the database.
        """
        if self._client is None:
            try:
                self._client = MessageDB.from_url(
                    self.config["database_uri"], **self._pool_kwargs
                )
            except psycopg2.OperationalError as exc:
                raise ConfigurationError(
                    f"Unable to connect to Event Store - {exc!s}"
                ) from exc

        return self._client

    def write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        """Write a message to the event store."""
        try:
            position: int = self.get_connection().write(
                stream_name,
                message_type,
                dict(data),
                dict(metadata) if metadata is not None else None,
                expected_version,
            )
        except ValueError as exc:
            # The client re-raises every database error as a ValueError and
            # keeps the psycopg2 error as its cause. write_message raises
            # P0001 for nothing but a wrong expected version, so read the code
            # off the cause instead of matching the localized message text.
            if getattr(exc.__cause__, "pgcode", None) == "P0001":
                text = str(exc)
                raise ExpectedVersionError(
                    text.partition(":")[2].strip() or text
                ) from exc
            raise
        return position

    def get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return _raw(
            self.get_connection().read_stream(
                stream_name, position=position, no_of_messages=limit
            )
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
        if (consumer_group_member is None) != (consumer_group_size is None):
            raise ValueError(
                "consumer_group_member and consumer_group_size must be given together"
            )
        # Message DB's ``category()`` matches the category exactly, so a read
        # of ``user`` returns no ``poweruser`` streams.
        return _raw(
            self.get_connection().read_category(
                category,
                position=position,
                no_of_messages=limit,
                consumer_group_member=consumer_group_member,
                consumer_group_size=consumer_group_size,
            )
        )

    def get_all_messages(
        self, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        # The client's own ``$all`` query filters ``global_position > position``
        # and so skips a row. Reads include ``position`` (ADR-0024), so supply
        # a query that does.
        return _raw(
            self.get_connection().read(
                "$all", sql=_ALL_SQL, position=position, no_of_messages=limit
            )
        )

    def get_last_stream_message(self, stream_name: str) -> RawMessage | None:
        message = self.get_connection().read_last_message(stream_name)
        return cast(RawMessage, message) if message is not None else None

    def get_last_category_message(self, category: str) -> RawMessage | None:
        return _first(
            self.get_connection().read(
                category, sql=_LAST_IN_CATEGORY_SQL, no_of_messages=1
            )
        )

    def get_last_message(self) -> RawMessage | None:
        return _first(
            self.get_connection().read("$all", sql=_LAST_SQL, no_of_messages=1)
        )

    def stream_ids(self, category: str) -> list[str]:
        """Return unique aggregate identifiers for a stream category.

        Delegates to the MessageDB client which uses an efficient SQL
        DISTINCT query, avoiding loading all messages into memory.
        """
        identifiers: list[str] = self.get_connection().stream_identifiers(category)
        return identifiers

    def ping(self) -> bool:
        """Run ``SELECT 1`` on a pooled connection. Never raises.

        A pooled connection that the server dropped while it stayed up is
        closed, and the check runs once more on a fresh connection.
        """
        try:
            pool = self.get_connection().connection_pool
            return _select_one(pool) or _select_one(pool)
        except Exception:  # an unreachable database reports False; logged
            # Health checks call this on every poll, so an outage logs at
            # debug instead of a warning per poll.
            logger.debug("Message DB ping failed", exc_info=True)
            return False

    def health(self) -> EventStoreHealth:
        return EventStoreHealth(reachable=self.ping(), pool=self._pool_stats())

    def _pool_stats(self) -> PoolStats | None:
        if self._client is None:
            return None
        # The client exposes no pool counters, so read them off the psycopg2
        # ``ThreadedConnectionPool`` it wraps: ``_used`` holds the connections
        # in use and ``_pool`` the idle ones. That pool never opens more than
        # ``maxconn`` connections, so nothing overflows.
        pool = self._client.connection_pool._connection_pool
        return PoolStats(
            size=pool.maxconn,
            checked_out=len(pool._used),
            overflow=0,
            checked_in=len(pool._pool),
        )

    def close(self) -> None:
        """Close the event store and release all pooled connections."""
        if self._client is not None:
            self._client.connection_pool.closeall()
            self._client = None

    def clear(self) -> None:
        """Empty the store's messages. Test-harness use only.

        Delegates to :func:`_truncate_message_store`; see its docstring for the
        Docker-only connection convention.
        """
        _truncate_message_store(self.domain.config["event_store"]["database_uri"])


_SELECT_COLUMNS = (
    "SELECT "
    "id::varchar, stream_name::varchar, type::varchar, position::bigint, "
    "global_position::bigint, data::varchar, metadata::varchar, time::timestamp "
    "FROM messages "
)

_ALL_SQL = (
    _SELECT_COLUMNS + "WHERE global_position >= %(position)s "
    "ORDER BY global_position ASC "
    "LIMIT %(batch_size)s"
)

# ``category()`` is Message DB's own function, so the match is exact. A
# ``LIKE 'user%'`` filter would also match ``users-1``.
_LAST_IN_CATEGORY_SQL = (
    _SELECT_COLUMNS + "WHERE category(stream_name) = %(stream_name)s "
    "ORDER BY global_position DESC "
    "LIMIT %(batch_size)s"
)

_LAST_SQL = _SELECT_COLUMNS + "ORDER BY global_position DESC LIMIT %(batch_size)s"


def _select_one(pool: ConnectionPool) -> bool:
    """Run ``SELECT 1`` on one pooled connection.

    Returns False and closes the connection when the query fails. Raises when
    the pool cannot hand out a connection.
    """
    conn = pool.get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        conn.rollback()
    except psycopg2.Error:
        pool.release(conn, close=True)
        return False
    pool.release(conn)
    return True


def _raw(rows: list[dict[str, Any]]) -> list[RawMessage]:
    return cast("list[RawMessage]", rows)


def _first(rows: list[dict[str, Any]]) -> RawMessage | None:
    return cast(RawMessage, rows[0]) if rows else None


_PORT_CHECK: type[EventStorePort] = MessageDBStore
