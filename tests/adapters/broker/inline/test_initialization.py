"""Tests for InlineBroker initialization and setup."""

import pytest

from protean.adapters.broker.inline import InlineBroker


@pytest.fixture(autouse=True)
def init_domain(test_domain):
    test_domain.init(traverse=False)


def test_that_a_concrete_broker_can_be_initialized_successfully(test_domain):
    broker = InlineBroker("dummy_name", test_domain, {})
    assert broker is not None


def test_that_domain_initializes_broker_from_config(test_domain):
    assert len(list(test_domain.brokers)) == 1
    assert isinstance(list(test_domain.brokers.values())[0], InlineBroker)


def test_that_inline_is_the_configured_broker(test_domain):
    assert "default" in test_domain.brokers
    broker = test_domain.brokers["default"]
    assert isinstance(broker, InlineBroker)
    assert broker.__broker__ == "inline"


def test_broker_configuration_parameters(test_domain):
    """Test that broker is initialized with correct configuration parameters."""
    broker = test_domain.brokers["default"]
    assert hasattr(broker, "_max_retries")
    assert hasattr(broker, "_retry_delay")
    assert hasattr(broker, "_backoff_multiplier")
    assert hasattr(broker, "_message_timeout")
    assert hasattr(broker, "_enable_dlq")
    assert hasattr(broker, "_operation_state_ttl")


def test_broker_internal_data_structures_initialization(test_domain):
    """Test that broker initializes all required internal data structures."""
    broker = test_domain.brokers["default"]
    assert hasattr(broker, "_messages")
    assert hasattr(broker, "_consumer_groups")
    assert hasattr(broker, "_in_flight")
    assert hasattr(broker, "_failed_messages")
    assert hasattr(broker, "_retry_counts")
    assert hasattr(broker, "_consumer_positions")
    assert hasattr(broker, "_message_ownership")
    assert hasattr(broker, "_dead_letter_queue")
    assert hasattr(broker, "_operation_states")
