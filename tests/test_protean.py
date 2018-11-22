
from click.testing import CliRunner

from protean.cli import cli


def test_main():
    runner = CliRunner()
    result = runner.invoke(cli, ['echo'])

    assert result.output == '()\n'
    assert result.exit_code == 0
