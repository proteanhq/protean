from typer.testing import CliRunner

from protean.cli.docs import app


def test_main():
    runner = CliRunner()
    result = runner.invoke(app)

    assert result.exit_code == 0
