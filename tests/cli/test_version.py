from typer.testing import CliRunner

from protean.cli import app


def test_main():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])

    from protean import __version__

    assert result.output == f"Protean {__version__}\n"
    assert result.exit_code == 0
