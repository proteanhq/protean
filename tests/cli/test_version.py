from typer.testing import CliRunner

from protean.cli import app


def test_main():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])

    from protean import __version__

    assert result.output == "Protean {protean_version}\n".format(
        protean_version=__version__
    )
    assert result.exit_code == 0
