"""Run the examples on ``docs/reference/adapters/broker/inline.md``."""

import subprocess
import sys

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.broker.redis import RedisBroker
from tests.docs.support import DOCS_SRC, REPO_ROOT, domain_from_config, load_example
from tests.shared import REDIS_URI

pytestmark = pytest.mark.no_test_domain


def test_subscriber_is_called_on_publish():
    example = load_example("adapters/broker/inline/001.py")

    assert example.created == ["123"]


def test_each_consumer_group_receives_every_message():
    example = load_example("adapters/broker/inline/001.py")

    expected = {"type": "order.created", "order_id": "A1"}
    assert example.billing_message == expected
    assert example.shipping_message == expected


def test_a_group_gets_each_message_once():
    example = load_example("adapters/broker/inline/001.py")

    with example.domain.domain_context():
        broker = example.domain.brokers["default"]
        broker.publish("invoices", {"invoice_id": "I1"})

        identifier, message = broker.get_next("invoices", "billing")
        assert message == {"invoice_id": "I1"}
        # Not acknowledged yet, and still not handed out a second time
        assert broker.get_next("invoices", "billing") is None
        assert broker.ack("invoices", identifier, "billing") is True


def test_domain_fixture_example_defines_a_subscriber():
    example = load_example("adapters/broker/inline/002.py")

    assert example.processed == []
    assert example.testing_domain.config["message_processing"] == "sync"


def test_domain_fixture_example_passes_under_pytest():
    # Run the file the way a reader would: as a pytest module, with its own
    # fixtures. A collection warning (for example a class named Test*) fails it.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(DOCS_SRC / "adapters/broker/inline/002.py"),
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
            "--import-mode=importlib",
            "-W",
            "error::pytest.PytestCollectionWarning",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


RETRY_OPTIONS = "adapters/broker/inline/retry_options.toml"


def _inline_broker(tmp_path, text=None):
    domain = domain_from_config(RETRY_OPTIONS, tmp_path, text=text)
    domain.init(traverse=False)
    with domain.domain_context():
        broker = domain.brokers["default"]
    assert type(broker) is InlineBroker
    return broker


def _retry_options(broker):
    return (
        broker._max_retries,
        broker._retry_delay,
        broker._backoff_multiplier,
        broker._message_timeout,
        broker._enable_dlq,
    )


def test_retry_options_shown_reach_the_broker(tmp_path):
    broker = _inline_broker(tmp_path)

    assert _retry_options(broker) == (3, 1.0, 2.0, 300.0, True)


def test_changed_retry_options_reach_the_broker(tmp_path):
    # The documented values equal the broker's defaults, so change each one
    # to show that the broker reads the key.
    text = (DOCS_SRC / RETRY_OPTIONS).read_text()
    for old, new in [
        ("max_retries = 3", "max_retries = 5"),
        ("retry_delay = 1.0", "retry_delay = 0.5"),
        ("backoff_multiplier = 2.0", "backoff_multiplier = 3.0"),
        ("message_timeout = 300.0", "message_timeout = 60.0"),
        ("enable_dlq = true", "enable_dlq = false"),
    ]:
        assert old in text
        text = text.replace(old, new)
    broker = _inline_broker(tmp_path, text)

    assert _retry_options(broker) == (5, 0.5, 3.0, 60.0, False)


def test_development_section_uses_the_inline_broker(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "dev")
    domain = domain_from_config("adapters/broker/inline/environments.toml", tmp_path)
    domain.init(traverse=False)

    with domain.domain_context():
        assert type(domain.brokers["default"]) is InlineBroker


@pytest.mark.redis
def test_production_section_uses_the_redis_broker(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "prod")
    monkeypatch.setenv("REDIS_URL", f"{REDIS_URI}/7")
    domain = domain_from_config("adapters/broker/inline/environments.toml", tmp_path)
    domain.init(traverse=False)

    with domain.domain_context():
        broker = domain.brokers["default"]

    assert type(broker) is RedisBroker
    assert broker.redis_instance.connection_pool.connection_kwargs["db"] == 7


def test_production_section_defaults_to_the_documented_uri(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "prod")
    monkeypatch.delenv("REDIS_URL", raising=False)
    domain = domain_from_config("adapters/broker/inline/environments.toml", tmp_path)

    assert domain.config["brokers"]["default"] == {
        "provider": "redis",
        "URI": "redis://localhost:6379/0",
    }
