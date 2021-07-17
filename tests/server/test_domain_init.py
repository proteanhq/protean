def test_that_domain_is_loaded_from_domain_file():
    from .dummy_domain import domain
    from protean.server import Server

    server = Server(domain=".dummy_domain.domain", package="tests.server")
    assert server.domain == domain


def test_that_the_default_broker_is_loaded_when_not_specified():
    from .dummy_domain import domain
    from protean.server import Server

    server = Server(domain=".dummy_domain.domain", package="tests.server")
    assert server.broker == domain.brokers["default"]
