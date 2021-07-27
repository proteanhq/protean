import pytest

from mock import patch

from protean.server import Server


@patch.object(Server, "push_messages")
def test_running_of_poll_loop_on_server_start(mock):
    server = Server.from_domain_file(
        domain="baz", domain_file="tests/server/support/dummy_domain.py", test_mode=True
    )
    server.run()

    mock.assert_called_once()
