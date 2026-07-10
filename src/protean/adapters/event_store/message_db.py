from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import psycopg2
from message_db.client import MessageDB

from protean.exceptions import ConfigurationError
from protean.port.event_store import BaseEventStore

if TYPE_CHECKING:
    from protean.domain import Domain


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

    def _read(
        self,
        stream_name: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read messages from the event store."""
        messages: list[dict[str, Any]] = self.client.read(
            stream_name, position=position, no_of_messages=no_of_messages
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
        """Utility function to empty messages, to be used only by test harness.

        This method is designed to work only with the postgres instance running in the configured docker container:
        User is locked to `postgres` and it is assumed that the default user does not have a password, both of which
        should not be the configuration in production.

        Any changes to configuration will need to updated here.
        """
        parsed = urlparse(self.domain.config["event_store"]["database_uri"])
        query_params = (
            dict(param.split("=") for param in parsed.query.split("&"))
            if parsed.query
            else {}
        )
        conn = psycopg2.connect(
            dbname=parsed.path[1:],
            user="postgres",
            port=parsed.port,
            host=parsed.hostname,
            sslmode=query_params.get("sslmode", "disable"),
        )

        cursor = conn.cursor()
        cursor.execute("TRUNCATE message_store.messages RESTART IDENTITY;")

        conn.commit()  # Apparently, psycopg2 requires a `commit` even if its a `TRUNCATE` command
        cursor.close()

        conn.close()
