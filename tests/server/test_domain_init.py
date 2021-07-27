from protean.server import Server


def test_that_domain_is_loaded_from_domain_file():
    server = Server.from_domain_file(
        domain="baz", domain_file="tests/server/support/dummy_domain.py"
    )
    assert server.domain is not None
    assert server.domain.domain_name == "FooBar"


def test_that_the_default_broker_is_loaded_when_not_specified():
    server = Server.from_domain_file(
        domain="baz", domain_file="tests/server/support/dummy_domain.py"
    )
    assert server.broker.name == "default"


def test_that_server_can_be_initialized_from_a_domain_object(test_domain):
    server = Server(test_domain)
    assert server.domain == test_domain
