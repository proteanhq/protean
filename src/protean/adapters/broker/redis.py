import redis

from typing import Union

from protean.port.broker import BaseBroker
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent


class RedisBroker(BaseBroker):
    def __init__(self, name, domain, conn_info):
        super().__init__(name, domain, conn_info)

        self.conn_pool = redis.ConnectionPool.from_url(conn_info["URI"])

    def get_connection(self) -> redis.Connection:
        """Retrieve an active connection from connection pool
        """
        return self.conn_pool.get_connection("_")

    def release_connection(self, connection: redis.Connection):
        """Release connection back to the connection pool
        """
        return self.conn_pool.release(connection)

    def send_message(self, initiator_obj):
        """Placeholder method for brokers to accept incoming events"""
        pass

    def publish(self, message: Union[BaseCommand, BaseEvent]):
        pass
