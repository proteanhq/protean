"""Fixtures for the broker port's conformance suite.

The conformance plugin builds the domain with the adapter under test as its
default broker, and clears and closes that adapter after each test.
"""

import pytest

from protean.domain import Domain
from protean.infra.broker import Broker


@pytest.fixture
def broker(test_domain: Domain) -> Broker:
    """The `Broker` service over the adapter under test."""
    return test_domain.brokers["default"]
