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


def test_running_of_poll_loop_on_server_start():
    pass


def test_publishing_an_event():
    pass


def test_publishing_an_event_asynchronously():
    pass


def test_publishing_a_command():
    pass


def test_publishing_a_command_asynchronously():
    pass


def test_retrieval_of_message_by_async_server():
    pass


def test_that_event_handler_is_invoked_on_event_message():
    pass


def test_multiple_event_handler_invocation_on_event_message():
    pass


def test_that_command_handler_is_invoked_on_command_message():
    pass


def test_that_event_is_marked_as_picked_up():
    # Should we have the status in a single event table,
    #   Or should we have a duplicate event log table emptied on event pick up,
    #   Or should we have a jobs table?
    pass


def test_that_command_is_marked_as_picked_up():
    # See comments above
    pass


def test_that_event_is_marked_as_processed_successfully():
    pass


def test_that_command_is_marked_as_processed_successfully():
    pass
