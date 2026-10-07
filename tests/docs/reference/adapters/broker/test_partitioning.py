"""Run the examples on ``docs/reference/adapters/broker/partitioning.md``."""

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.exceptions import ProteanException
from protean.port.broker import BrokerCapabilities
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture(scope="module")
def example():
    return load_example("adapters/broker/partitioning/001.py")


def test_broker_advertises_stream_partitioning(example):
    capabilities = example.MyBroker.capabilities.fget(None)

    assert BrokerCapabilities.STREAM_PARTITIONING in capabilities
    assert BrokerCapabilities.ORDERED_MESSAGING in capabilities


def test_inline_broker_does_not_advertise_stream_partitioning():
    capabilities = InlineBroker.capabilities.fget(None)

    assert BrokerCapabilities.STREAM_PARTITIONING not in capabilities


def test_lease_lost_error_is_a_protean_exception(example):
    assert issubclass(example.LeaseLostError, ProteanException)
