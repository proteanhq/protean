from mock import patch

from protean import Engine


@patch.object(Engine, "start_event_handler_subscriptions")
@patch.object(Engine, "start_command_handler_subscriptions")
def test_running_subscriptions_on_engine_start(
    mock_command_handler_subscriptions, mock_event_handler_subscriptions
):
    engine = Engine.from_domain_file(
        domain="baz", domain_file="tests/server/dummy_domain.py", test_mode=True
    )
    engine.run()

    mock_command_handler_subscriptions.assert_called_once()
    mock_event_handler_subscriptions.assert_called_once()


def test_shutdown_on_stop(test_domain):
    engine = Engine(test_domain)
    assert engine.SHUTTING_DOWN is False

    engine.stop()
    assert engine.SHUTTING_DOWN is True
