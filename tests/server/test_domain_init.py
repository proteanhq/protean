import pytest

from protean.server import Server


def test_that_domain_is_loaded_from_domain_file():
    server = Server(domain="baz", domain_file="tests/server/support/dummy_domain.py")
    assert server.domain is not None
    assert server.domain.domain_name == "FooBar"


def test_that_the_default_broker_is_loaded_when_not_specified():
    server = Server(domain="baz", domain_file="tests/server/support/dummy_domain.py")
    assert server.broker.name == "default"
