# --8<-- [start:full]
import os

from protean import Domain
from protean.adapters.broker.redis import RedisBroker

domain = Domain(name="RedisStreams")
domain.config["brokers"]["default"] = {
    "provider": "redis",
    "URI": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    # Optional connection pool settings
    "max_connections": 10,
    "socket_timeout": 5,
}
domain.init(traverse=False)

with domain.domain_context():
    broker = domain.brokers["default"]
    assert isinstance(broker, RedisBroker)

    # XADD to the "user-events" stream
    broker.publish("user-events", {"type": "user.created", "user_id": "123"})

    # XREADGROUP as the "welcome-mailer" consumer group
    identifier, message = broker.get_next("user-events", "welcome-mailer")

    # XACK, so the message is no longer pending for the group
    acknowledged = broker.ack("user-events", identifier, "welcome-mailer")
# --8<-- [end:full]
