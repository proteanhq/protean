import psycopg2

from typing import List, Dict, Any

from message_db.client import MessageDB

from protean.port.event_store import BaseEventStore
from protean.exceptions import ConfigurationError


class MessageDBStore(BaseEventStore):
    def __init__(self, domain, conn_info) -> None:
        super().__init__("MessageDB", domain, conn_info)

        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                self._client = MessageDB.from_url(self.conn_info["DATABASE_URI"])
            except psycopg2.OperationalError as exc:
                raise ConfigurationError(
                    f"Unable to connect to Event Store - {str(exc)}"
                )

        return self._client

    def write(
        self,
        stream_name: str,
        message_type: str,
        data: Dict,
        metadata: Dict = None,
        expected_version: int = None,
    ) -> int:
        return self.client.write(
            stream_name, message_type, data, metadata, expected_version
        )

    def read(self, stream_name: str) -> List[Dict[str, Any]]:
        return self.client.read(stream_name)

    def read_last_message(self, stream_name) -> Dict[str, Any]:
        return self.client.read_last_message(stream_name)

    def _data_reset(self):
        """Utility function to empty messages, to be used only by test harness.

        This method is designed to work only with the postgres instance run in the configured docker container:
        Port is locked to 5433 and it is assumed that the default user does not have a password, both of which
        should not be the configuration in production.

        Any changes to docker configuration will need to updated here.
        """
        conn = psycopg2.connect(
            dbname="message_store", user="postgres", port=5433, host="localhost"
        )

        cursor = conn.cursor()
        cursor.execute("TRUNCATE message_store.messages RESTART IDENTITY;")

        conn.commit()  # Apparently, psycopg2 requires a `commit` even if its a `TRUNCATE` command
        cursor.close()

        conn.close()
