from mock import patch

from protean.server import Server


@patch.object(Server, "push_messages")
@patch.object(Server, "poll_for_messages")
@patch.object(Server, "poll_for_jobs")
def test_running_of_poll_loop_on_server_start(
    mock_poll_for_jobs, mock_poll_for_messages, mock_push_messages
):
    server = Server.from_domain_file(
        domain="baz", domain_file="tests/server/support/dummy_domain.py", test_mode=True
    )
    server.run()

    mock_push_messages.assert_called_once()
    mock_poll_for_messages.assert_called_once()
    mock_poll_for_jobs.assert_called_once()
