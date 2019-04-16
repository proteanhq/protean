
from click.testing import CliRunner

from protean.cli import main


def test_main():
    runner = CliRunner()
    result = runner.invoke(main, ['--version'])

    import platform
    from protean import __version__

    assert result.output == 'Python {python_version}\nProtean {protean_version}\n'.format(
        python_version=platform.python_version(), protean_version=__version__)
    assert result.exit_code == 0
