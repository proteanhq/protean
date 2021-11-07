import psycopg2

from uuid import uuid4
from psycopg2.extras import register_uuid, Json, RealDictCursor

from protean.exceptions import ConfigurationError

# Support UUID data type
# https://www.psycopg.org/docs/extras.html#uuid-data-type
register_uuid()


class MessageDB:
    """Message DB Event Store Implementation"""

    def __init__(self, domain, conn_info) -> None:
        self.domain = domain
        self.conn_info = conn_info

        self.name = "MessageDB"

        try:
            self._connection = psycopg2.connect(conn_info["DATABASE_URI"])
        except psycopg2.OperationalError as exc:
            raise ConfigurationError(f"Unable to connect to Event Store - {str(exc)}")

        self._cursor = self._connection.cursor(cursor_factory=RealDictCursor)

    def write(
        self, stream_name, message_type, data, metadata=None, expected_version=None
    ):
        self._cursor.execute(
            (
                "SELECT message_store.write_message(%(identifier)s, %(stream_name)s, %(type)s, "
                "%(data)s, %(metadata)s, %(expected_version)s);"
            ),
            {
                "identifier": str(uuid4()),
                "stream_name": stream_name,
                "type": message_type,
                "data": Json(data),
                "metadata": Json(metadata) if metadata else None,
                "expected_version": expected_version,
            },
        )
        self._connection.commit()

        result = self._cursor.fetchone()
        return result["write_message"]

    def read(self, stream_name, position, no_of_messages):
        if "-" in stream_name:
            sql = "SELECT * FROM get_stream_messages(%(stream_name)s, %(position)s, %(batch_size)s);"
        else:
            sql = "SELECT * FROM get_category_messages(%(stream_name)s, %(position)s, %(batch_size)s);"

        self._cursor.execute(
            sql,
            {
                "stream_name": stream_name,
                "position": position,
                "batch_size": no_of_messages,
            },
        )
        messages = self._cursor.fetchall()

        self._connection.commit()
        return messages

    def read_last_message(self, stream_name):
        self._cursor.execute(
            "SELECT * from get_last_stream_message(%(stream_name)s);",
            {"stream_name": stream_name},
        )

        message = self._cursor.fetchone()

        self._connection.commit()
        return message

    def _clear(self):
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
