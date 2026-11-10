"""Run the examples on ``docs/reference/adapters/broker/index.md``."""

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.broker.redis import RedisBroker
from protean.adapters.broker.redis_pubsub import RedisPubSubBroker
from tests.docs.support import domain_from_config, load_example
from tests.shared import REDIS_URI

pytestmark = pytest.mark.no_test_domain


def test_capability_checks_read_and_acknowledge_the_message():
    example = load_example("adapters/broker/index/001.py")

    assert len(example.messages) == 1
    _, message = example.messages[0]
    assert message == {"order_id": "A1"}

    with example.domain.domain_context():
        broker = example.domain.brokers["default"]
        # The example acknowledged the message, so acknowledging it again fails
        identifier, _ = example.messages[0]
        assert broker.ack("orders", identifier, "order-processor") is False
        assert broker.get_next("orders", "order-processor") is None


def test_subscriber_receives_published_message():
    example = load_example("adapters/broker/index/002.py")

    assert example.welcomed == ["user@example.com"]


def test_subscriber_ignores_other_event_types():
    example = load_example("adapters/broker/index/002.py")

    with example.domain.domain_context():
        example.domain.brokers.publish(
            stream="user-events",
            message={"event_type": "user.deleted", "email": "gone@example.com"},
        )

    assert example.welcomed == ["user@example.com"]


def test_publish_to_named_broker_lands_on_that_broker():
    example = load_example("adapters/broker/index/002.py")

    with example.domain.domain_context():
        notifications = example.domain.brokers["notifications"]
        _, message = notifications.get_next("notifications", "mailer")
        assert message == {
            "type": "email",
            "to": "user@example.com",
            "subject": "Welcome!",
        }
        # The default broker never saw the notification
        default = example.domain.brokers["default"]
        assert default.get_next("notifications", "mailer") is None


def test_empty_message_is_rejected():
    example = load_example("adapters/broker/index/002.py")

    assert example.error == {"message": ["Message cannot be empty"]}


def test_health_stats_shape():
    example = load_example("adapters/broker/index/002.py")

    assert example.health_stats["status"] == "healthy"
    assert example.health_stats["connected"] is True
    assert isinstance(example.health_stats["details"], dict)


@pytest.mark.redis
def test_configuration_shown_builds_three_brokers(tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_URL", REDIS_URI)
    domain = domain_from_config("adapters/broker/index/multiple_brokers.toml", tmp_path)
    domain.init(traverse=False)

    with domain.domain_context():
        brokers = {
            name: domain.brokers[name]
            for name in ("default", "notifications", "analytics")
        }

    assert type(brokers["default"]) is InlineBroker
    assert type(brokers["notifications"]) is RedisPubSubBroker
    assert type(brokers["analytics"]) is RedisBroker
    # The variable holds the server, and each URI keeps its own database
    dbs = {
        name: brokers[name].redis_instance.connection_pool.connection_kwargs["db"]
        for name in ("notifications", "analytics")
    }
    assert dbs == {"notifications": 0, "analytics": 1}


def test_configuration_shown_defaults_to_the_documented_uris(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    domain = domain_from_config("adapters/broker/index/multiple_brokers.toml", tmp_path)

    brokers = domain.config["brokers"]
    assert brokers["notifications"]["URI"] == "redis://localhost:6379/0"
    assert brokers["analytics"]["URI"] == "redis://localhost:6379/1"
