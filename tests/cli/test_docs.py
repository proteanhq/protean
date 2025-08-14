from unittest.mock import patch

from typer.testing import CliRunner

from protean.cli.docs import app


def test_main():
    runner = CliRunner()
    result = runner.invoke(app)

    # With no_args_is_help=True, invoking with no args shows help and exits with code 2
    assert result.exit_code == 2


def test_callback_function():
    """Test the callback function is called when app is invoked"""
    runner = CliRunner()
    # The callback function is called when the app is invoked
    # This test ensures line 20 (callback function) is covered
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


@patch("protean.cli.docs.subprocess.call")
def test_preview_command(mock_subprocess_call):
    """Test the preview command calls subprocess with correct arguments"""
    runner = CliRunner()
    result = runner.invoke(app, ["preview"])

    # Verify subprocess.call was called with correct arguments
    mock_subprocess_call.assert_called_once_with(
        ["mkdocs", "serve", "--dev-addr=0.0.0.0:8000"]
    )
    assert result.exit_code == 0


@patch("protean.cli.docs.subprocess.call")
def test_preview_command_keyboard_interrupt(mock_subprocess_call):
    """Test the preview command handles KeyboardInterrupt gracefully"""
    # Mock subprocess.call to raise KeyboardInterrupt
    mock_subprocess_call.side_effect = KeyboardInterrupt()

    runner = CliRunner()
    result = runner.invoke(app, ["preview"])

    # The command should handle KeyboardInterrupt and exit gracefully
    mock_subprocess_call.assert_called_once_with(
        ["mkdocs", "serve", "--dev-addr=0.0.0.0:8000"]
    )
    assert result.exit_code == 0
