
from click.testing import CliRunner

from protean.cli import main


def test_main():
    runner = CliRunner()
    result = runner.invoke(main, ['echo'])

    assert result.output == '()\n'
    assert result.exit_code == 0
