from click.testing import CliRunner

from protean.cli import main


def test_main():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])

    from protean import __version__

    assert result.output == "main, version {protean_version}\n".format(
        protean_version=__version__
    )
    assert result.exit_code == 0
