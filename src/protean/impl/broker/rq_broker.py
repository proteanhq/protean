# Standard Library Imports
import logging
import logging.config
import os

# Protean
from protean.core.broker.base import BaseBroker
from protean.core.domain_event import BaseDomainEvent
from protean.domain import Domain
from protean.utils import fully_qualified_name
from protean.utils.inflection import underscore
from redis import Redis
from rq import Queue, Worker, get_current_connection, push_connection

logger = logging.getLogger("protean.impl.broker.rq")


class ProteanRQWorker(Worker):
    """Custom RQ Worker class to be able to initialize and use a Protean domain"""

    def __init__(self, queues, **kwargs):
        # Ensure rest of the Worker functionality of RQ remains the same
        super().__init__(queues, **kwargs)

        # Initialize and Configure a Protean Domain
        self.domain = Domain("RQ")
        config_path = os.environ["PROTEAN_RQ_CONFIG_FILE"]
        self.domain.config.from_pyfile(config_path)
        self.domain.domain_context().push()

        logging.config.dictConfig(self.domain.config["LOGGING_CONFIG"])


class RqBroker(BaseBroker):
    def __init__(self, name, domain, conn_info):
        super().__init__(name, domain, conn_info)

        # Initialize Redis Connection
        push_connection(Redis.from_url(self.conn_info["URI"]))

    def get_connection(self):
        """Get the connection object to the broker"""
        return get_current_connection()

    def send_message(self, initiator_obj):
        if isinstance(initiator_obj, BaseDomainEvent):
            for subscriber_cls in self._subscribers[
                fully_qualified_name(initiator_obj.__class__)
            ]:
                q = Queue(
                    name=underscore(subscriber_cls.__name__),
                    is_async=self.conn_info["IS_ASYNC"],
                )
                q.enqueue(subscriber_cls.notify, initiator_obj.to_dict())
        else:
            self._command_handlers[fully_qualified_name(initiator_obj.__class__)]
            q.enqueue(
                underscore(initiator_obj.__class__.__name__), initiator_obj.to_dict()
            )
