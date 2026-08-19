from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlparse

import psycopg2
from message_db.client import MessageDB

from protean.exceptions import ConfigurationError
from protean.port.event_store import BaseEventStore

if TYPE_CHECKING:
    from protean.domain import Domain


def _truncate_message_store(database_uri: str) -> None:
    """Empty the Message-DB store at ``database_uri``. Test-harness use only.

    Works only against the Postgres instance in the configured Docker container:
    it connects as the ``postgres`` superuser, which is assumed to have no
    password. Neither holds in production, so this must never run there. Any
    change to the connection convention has to be made here, the single place
    both ``MessageDBStore._data_reset`` and the test-suite reset go through.
    """
    parsed = urlparse(database_uri)
    # ``parse_qsl`` tolerates odd query strings (a trailing ``&``, an empty
    # segment, a segment with no ``=``) that a hand-rolled ``split`` would choke
    # on, so a slightly different ``database_uri`` cannot break truncation.
    query_params = dict(parse_qsl(parsed.query))
    conn = psycopg2.connect(
        dbname=parsed.path[1:],
        user="postgres",
        port=parsed.port,
        host=parsed.hostname,
        sslmode=query_params.get("sslmode", "disable"),
    )
    try:
        cursor = conn.cursor()
        cursor.execute("TRUNCATE message_store.messages RESTART IDENTITY;")
        conn.commit()  # psycopg2 requires a commit even for a TRUNCATE
        cursor.close()
    finally:
        conn.close()


class MessageDBStore(BaseEventStore):
    """MessageDB event store adapter.

    Connection pool parameters can be configured via conn_info:
        - max_connections: Maximum number of connections in the pool
    """

    # Keys from conn_info that are forwarded to MessageDB connection pool
    _POOL_KEYS = frozenset({"max_connections"})

    def __init__(self, domain: Domain, conn_info: dict[str, Any]) -> None:
        super().__init__("MessageDB", domain, conn_info)

        self._client: MessageDB | None = None
        self._pool_kwargs: dict[str, Any] = {
            key: value for key, value in conn_info.items() if key in self._POOL_KEYS
        }

    @property
    def client(self) -> MessageDB:
        """Return the MessageDB client instance."""
        if self._client is None:
            try:
                self._client = MessageDB.from_url(
                    self.conn_info["database_uri"], **self._pool_kwargs
                )
            except psycopg2.OperationalError as exc:
                raise ConfigurationError(
                    f"Unable to connect to Event Store - {exc!s}"
                ) from exc

        return self._client

    def _write(
        self,
        stream_name: str,
        message_type: str,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        """Write a message to the event store."""
        position: int = self.client.write(
            stream_name, message_type, data, metadata, expected_version
        )
        return position

    # The message-db client's built-in ``$all`` query is a strict, unordered
    # ``global_position > position LIMIT n`` — it skips the first position and,
    # having no ``ORDER BY`` before the ``LIMIT``, returns an arbitrary subset
    # rather than the lowest-``global_position`` page. Protean's read contract is
    # an inclusive, ``global_position``-ordered page (subscriptions and outbox
    # reconciliation page from ``last_global_position + 1``), consistent with
    # category reads (``get_category_messages`` uses ``global_position >= position
    # ORDER BY global_position ASC``) and the memory adapter, so supply a
    # corrected statement.
    _ALL_STREAM_SQL = (
        "SELECT "
        "id::varchar, stream_name::varchar, type::varchar, position::bigint, "
        "global_position::bigint, data::varchar, metadata::varchar, time::timestamp "
        "FROM messages "
        "WHERE global_position >= %(position)s "
        "ORDER BY global_position ASC "
        "LIMIT %(batch_size)s"
    )

    def _read(
        self,
        stream_name: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read messages from the event store.

        Category and specific-stream reads use the client's own (already
        inclusive, ``global_position``/stream-position ordered) statements; only
        ``$all`` needs a corrected query (see :attr:`_ALL_STREAM_SQL`).
        """
        if sql is None and stream_name == "$all":
            sql = self._ALL_STREAM_SQL
        messages: list[dict[str, Any]] = self.client.read(
            stream_name, sql=sql, position=position, no_of_messages=no_of_messages
        )
        return messages

    def _read_last_message(self, stream_name: str) -> dict[str, Any] | None:
        """Read the last message from ``stream_name``.

        The client's ``get_last_stream_message()`` resolves only *specific*
        streams (``category-id``); it returns ``None`` for category streams
        (``$all`` or a bare ``category``). Fall back to reading the stream and
        taking the last message so callers reading a category stream — notably
        ``reconcile_outbox``, which reads ``$all`` (ADR-0015) — get the newest
        message instead of a spurious ``None``.
        """
        message: dict[str, Any] | None = self.client.read_last_message(stream_name)
        if message is not None:
            return message

        # TODO: page-in the whole stream only because the message-db client has
        # no category tail-read; replace with a bounded reverse read when it does.
        # The client's ``$all`` query has no ``ORDER BY``, so pick the newest by
        # ``global_position`` rather than trusting row order (``messages[-1]``).
        messages = self._read(stream_name, no_of_messages=1_000_000)
        if not messages:
            return None
        return max(messages, key=lambda m: m["global_position"])

    def _stream_head_position(self, stream_category: str) -> int:
        message = self._read_last_message(stream_category)
        return message.get("global_position", -1) if message else -1

    def _stream_identifiers(self, stream_category: str) -> list[str]:
        """Return unique aggregate identifiers for a stream category.

        Delegates to the MessageDB client which uses an efficient SQL
        DISTINCT query, avoiding loading all messages into memory.
        """
        identifiers: list[str] = self.client.stream_identifiers(stream_category)
        return identifiers

    def close(self) -> None:
        """Close the event store and release all pooled connections."""
        if self._client is not None:
            self._client.connection_pool.closeall()
            self._client = None

    def _data_reset(self) -> None:
        """Empty the store's messages. Test-harness use only.

        Delegates to :func:`_truncate_message_store`; see its docstring for the
        Docker-only connection convention.
        """
        _truncate_message_store(self.domain.config["event_store"]["database_uri"])
