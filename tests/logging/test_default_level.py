"""The default log level when no environment variable is set.

With ``PROTEAN_ENV``, ``ENV`` and ``ENVIRONMENT`` all unset, a domain logs at
INFO. Only an explicit ``development`` environment, or ``PROTEAN_LOG_LEVEL``,
selects DEBUG.
"""

import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.shared import change_working_directory_to

pytestmark = pytest.mark.no_test_domain

_ENV_VARS = (
    "PROTEAN_ENV",
    "ENV",
    "ENVIRONMENT",
    "PROTEAN_LOG_LEVEL",
    "PROTEAN_NO_AUTO_LOGGING",
)

# A newcomer's first script: build a domain, then catch a validation error.
SCRIPT = textwrap.dedent(
    """\
    from protean import Domain
    from protean.exceptions import ValidationError
    from protean.fields import String

    domain = Domain(name="Quiet")


    @domain.aggregate
    class Person:
        name = String(required=True)


    domain.init(traverse=False)

    with domain.domain_context():
        try:
            Person()
        except ValidationError:
            pass

    print("done")
    """
)


def _run_script(tmp_path: Path, **env_overrides: str) -> subprocess.CompletedProcess:
    """Run ``SCRIPT`` in a fresh interpreter, in a directory with no config file.

    A subprocess is needed because the test session sets ``PROTEAN_ENV=test``
    and pytest installs its own handlers on the root logger, either of which
    would hide the default under test.
    """
    script = tmp_path / "script.py"
    script.write_text(SCRIPT)
    env = {k: v for k, v in os.environ.items() if k not in _ENV_VARS}
    env.update(env_overrides)
    result = subprocess.run(
        # The "No configuration file found" UserWarning is not a log line.
        [sys.executable, "-W", "ignore::UserWarning", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "done"
    return result


class TestFreshScript:
    def test_unset_environment_writes_no_log_lines(self, tmp_path):
        result = _run_script(tmp_path)

        assert result.stderr == ""

    @pytest.mark.parametrize(
        "env",
        [{"PROTEAN_ENV": "development"}, {"PROTEAN_LOG_LEVEL": "DEBUG"}],
        ids=["protean_env_development", "protean_log_level_debug"],
    )
    def test_debug_lines_return_on_request(self, tmp_path, env):
        result = _run_script(tmp_path, **env)

        assert "Loaded provider plugin: memory" in result.stderr


class TestShellDefaultLevel:
    @pytest.fixture(autouse=True)
    def _restore(self, monkeypatch):
        for var in _ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        original_path = sys.path[:]
        cwd = Path.cwd()
        root = logging.getLogger()
        original_handlers, original_level = root.handlers[:], root.level

        yield

        root.handlers[:] = original_handlers
        root.setLevel(original_level)
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_protean_shell_logs_at_info(self):
        pytest.importorskip("IPython")
        change_working_directory_to("test7")
        # Auto-configuration skips when the root logger has handlers, and
        # pytest adds its own.
        logging.getLogger().handlers.clear()

        result = CliRunner().invoke(app, ["shell", "--domain", "publishing7.py"])

        assert result.exit_code == 0, result.output
        assert logging.getLogger().level == logging.INFO
        assert logging.getLogger("protean").getEffectiveLevel() == logging.INFO
