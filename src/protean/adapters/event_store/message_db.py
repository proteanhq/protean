from typing import Any, Dict, List
from urllib.parse import urlparse

import psycopg2
from message_db.client import MessageDB

from protean.exceptions import ConfigurationError
from protean.port.event_store import BaseEventStore


class MessageDBStore(BaseEventStore):
    def __init__(self, domain, conn_info) -> None:
        super().__init__("MessageDB", domain, conn_info)

        self._client = None

    @property
    def client(self):
        """Return the MessageDB client instance."""
        if self._client is None:
            try:
                self._client = MessageDB.from_url(self.conn_info["database_uri"])
            except psycopg2.OperationalError as exc:
                raise ConfigurationError(
                    f"Unable to connect to Event Store - {str(exc)}"
                )

        return self._client

    def _write(
        self,
        stream_name: str,
        message_type: str,
        data: Dict,
        metadata: Dict | None = None,
        expected_version: int | None = None,
    ) -> int:
        """Write a message to the event store."""
        return self.client.write(
            stream_name, message_type, data, metadata, expected_version
        )

    def _read(
        self,
        stream_name: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Read messages from the event store."""
        return self.client.read(
            stream_name, position=position, no_of_messages=no_of_messages
        )

    def _read_last_message(self, stream_name) -> Dict[str, Any]:
        """Read the last message from the event store."""
        return self.client.read_last_message(stream_name)

    def _data_reset(self):
        """Utility function to empty messages, to be used only by test harness.

        This method is designed to work only with the postgres instance running in the configured docker container:
        User is locked to `postgres` and it is assumed that the default user does not have a password, both of which
        should not be the configuration in production.

        Any changes to configuration will need to updated here.
        """
        parsed = urlparse(self.domain.config["event_store"]["database_uri"])
        conn = psycopg2.connect(
            dbname=parsed.path[1:],
            user="postgres",
            port=parsed.port,
            host=parsed.hostname,
        )

        cursor = conn.cursor()
        cursor.execute("TRUNCATE message_store.messages RESTART IDENTITY;")

        conn.commit()  # Apparently, psycopg2 requires a `commit` even if its a `TRUNCATE` command
        cursor.close()

        conn.close()
