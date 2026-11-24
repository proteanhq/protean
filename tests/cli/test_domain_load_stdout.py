"""A domain module's own output stays off a CLI command's stdout.

Anything a domain module writes while the CLI imports, initializes or checks it
(a ``print()``, or a structlog line written before logging is configured) goes
to stderr, so a command's machine payload on stdout stays parseable (#2103,
#2024).

Each command runs as ``python -m protean ...`` in a child process with no
logging flags: a module imports once per process, and an in-process run would
see logging already configured by earlier tests. Each module sits in its own
directory, because ``Domain.init`` imports every module in the domain's
directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_test_domain

_NOISE = """\
import structlog

print("LOADING")
structlog.get_logger("noisy").warning("LOGGED")
"""

_FAILING_MODULE = _NOISE + 'raise RuntimeError("boom")\n'

_LOADING_MODULE = (
    _NOISE
    + """
from protean import Domain
from protean.fields import String

domain = Domain(name="Noisy")


@domain.aggregate
class Account:
    name = String(max_length=50)


@domain.event(part_of=Account)
class AccountOpened:
    name = String(max_length=50)
"""
)


_LINT_RULE = """\
print("LINTIMPORT")


def check_names(ir):
    print("LINTRUN")
    return []
"""


def _run_protean(
    cwd: Path, *args: str, pythonpath: Path | None = None
) -> subprocess.CompletedProcess[str]:
    # A caller's ``PROTEAN_LOG_*`` setting could silence the ``LOGGED`` line.
    env = {
        k: v
        for k, v in os.environ.items()
        if k != "PROTEAN_DOMAIN" and not k.startswith("PROTEAN_LOG_")
    }
    if pythonpath is not None:
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(pythonpath), env.get("PYTHONPATH", "")) if p
        )
    return subprocess.run(
        [sys.executable, "-B", "-m", "protean", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
    )


def _write_module(directory: Path, name: str, source: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def ir_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An IR file built from the loading module, for ``--right`` and ``ir check``."""
    root = tmp_path_factory.mktemp("ir_baseline")
    module = _write_module(root / "domain", "noisy_loading", _LOADING_MODULE)
    result = _run_protean(root, "ir", "show", "--domain", str(module))
    assert result.returncode == 0, result.stderr
    path = root / "ir.json"
    path.write_text(result.stdout, encoding="utf-8")
    return path


class TestAFailingModuleKeepsStdoutForTheCommand:
    """A module that prints, logs, then raises: the output is on stderr."""

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(("upgrade-check",), id="upgrade-check-text"),
            pytest.param(
                ("upgrade-check", "--format", "json"), id="upgrade-check-json"
            ),
            pytest.param(("ir", "diff"), id="ir-diff-text"),
            pytest.param(("ir", "diff", "--format", "json"), id="ir-diff-json"),
        ],
    )
    def test_stdout_is_empty_and_stderr_has_the_error(
        self, tmp_path: Path, ir_file: Path, args: tuple[str, ...]
    ) -> None:
        module = _write_module(tmp_path / "domain", "noisy_failing", _FAILING_MODULE)
        extra = ("--right", str(ir_file)) if args[0] == "ir" else ()

        result = _run_protean(tmp_path, *args, *extra, "--domain", str(module))

        assert result.returncode == 2, result.stderr
        assert result.stdout == ""
        assert "LOADING" in result.stderr
        assert "LOGGED" in result.stderr
        assert "boom" in result.stderr

    def test_events_catalog_prints_only_the_error_envelope(
        self, tmp_path: Path
    ) -> None:
        module = _write_module(tmp_path / "domain", "noisy_failing", _FAILING_MODULE)

        result = _run_protean(
            tmp_path, "events", "catalog", "--json", "--domain", str(module)
        )

        assert result.returncode == 2, result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["status"] == "error"
        assert "boom" in envelope["data"]["error"]
        assert "LOADING" in result.stderr
        assert "LOGGED" in result.stderr
        assert "boom" in result.stderr

    def test_verify_prints_only_the_envelope(self, tmp_path: Path) -> None:
        module = _write_module(tmp_path / "domain", "noisy_failing", _FAILING_MODULE)

        result = _run_protean(tmp_path, "verify", "--json", "--domain", str(module))

        assert result.returncode == 3, result.stderr
        envelope = json.loads(result.stdout)
        assert "boom" in envelope["data"]["stages"]["init"]["error"]
        assert "LOADING" in result.stderr
        assert "LOGGED" in result.stderr


def _assert_a_result_payload(result: subprocess.CompletedProcess[str]) -> None:
    """Stdout is one JSON document, and not an error envelope."""
    payload = json.loads(result.stdout)
    assert isinstance(payload, (dict, list)), result.stderr
    if isinstance(payload, dict):
        assert payload.get("status") != "error", result.stdout


class TestALoadingModuleKeepsStdoutParseable:
    """A module that prints and logs, then defines a domain: stdout is JSON."""

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(("upgrade-check", "--format", "json"), id="upgrade-check"),
            pytest.param(("check", "--format", "json"), id="check"),
            pytest.param(("ir", "show"), id="ir-show"),
            pytest.param(("ir", "diff", "--format", "json"), id="ir-diff"),
            pytest.param(("ir", "check", "--format", "json"), id="ir-check"),
            pytest.param(("schema", "show", "AccountOpened", "--raw"), id="schema"),
            pytest.param(("events", "catalog", "--json"), id="events-catalog"),
            pytest.param(("projection", "status", "--json"), id="projection-status"),
        ],
    )
    def test_stdout_parses_as_json(
        self, tmp_path: Path, ir_file: Path, args: tuple[str, ...]
    ) -> None:
        module = _write_module(tmp_path / "domain", "noisy_loading", _LOADING_MODULE)
        extra: tuple[str, ...] = ()
        if args[:2] == ("ir", "diff"):
            extra = ("--right", str(ir_file))
        elif args[:2] == ("ir", "check"):
            protean_dir = tmp_path / ".protean"
            protean_dir.mkdir()
            shutil.copy(ir_file, protean_dir / "ir.json")

        result = _run_protean(tmp_path, *args, *extra, "--domain", str(module))

        _assert_a_result_payload(result)
        assert "LOADING" not in result.stdout
        assert "LOGGED" not in result.stdout
        assert "LOADING" in result.stderr

    def test_ir_show_summary_keeps_the_module_output_off_stdout(
        self, tmp_path: Path
    ) -> None:
        module = _write_module(tmp_path / "domain", "noisy_loading", _LOADING_MODULE)

        result = _run_protean(
            tmp_path, "ir", "show", "--format", "summary", "--domain", str(module)
        )

        assert result.returncode == 0, result.stderr
        assert "Noisy" in result.stdout
        assert "LOADING" not in result.stdout
        assert "LOGGED" not in result.stdout
        assert "LOADING" in result.stderr

    def test_verify_prints_only_the_envelope(self, tmp_path: Path) -> None:
        module = _write_module(tmp_path / "domain", "noisy_loading", _LOADING_MODULE)

        result = _run_protean(tmp_path, "verify", "--json", "--domain", str(module))

        envelope = json.loads(result.stdout)
        assert envelope["data"]["stages"]["init"]["status"] == "pass", result.stdout
        assert "check" in envelope["data"]["stages"]
        assert "LOADING" not in result.stdout
        assert "LOGGED" not in result.stdout
        assert "LOADING" in result.stderr


class TestDatabaseCommandsKeepTheModuleOutputOffStdout:
    """``db check`` and a ``db`` command that loads without connecting."""

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(("db", "check"), id="db-check"),
            # ``--sql`` loads the domain with ``connect=False``.
            pytest.param(("db", "upgrade", "--sql"), id="db-upgrade-sql"),
        ],
    )
    def test_module_output_goes_to_stderr(
        self, tmp_path: Path, args: tuple[str, ...]
    ) -> None:
        module = _write_module(tmp_path / "domain", "noisy_loading", _LOADING_MODULE)

        result = _run_protean(tmp_path, *args, "--domain", str(module))

        # No migrations folder exists, so both commands stop with an error after
        # the load. The load itself must have run.
        assert "No migrations found" in result.stdout + result.stderr
        assert "LOADING" not in result.stdout
        assert "LOGGED" not in result.stdout
        assert "LOADING" in result.stderr


class TestALintRuleKeepsStdoutParseable:
    """A ``[lint].rules`` callable runs while the IR builds; its output is on stderr."""

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(("ir", "show"), id="ir-show"),
            pytest.param(("ir", "diff", "--format", "json"), id="ir-diff"),
            pytest.param(("schema", "show", "AccountOpened", "--raw"), id="schema"),
            pytest.param(("events", "catalog", "--json"), id="events-catalog"),
        ],
    )
    def test_stdout_parses_as_json(
        self, tmp_path: Path, ir_file: Path, args: tuple[str, ...]
    ) -> None:
        module = _write_module(tmp_path / "domain", "noisy_loading", _LOADING_MODULE)
        (tmp_path / "domain" / "domain.toml").write_text(
            '[lint]\nrules = ["noisy_lint_rule_2103.check_names"]\n', encoding="utf-8"
        )
        # The rule sits outside the domain directory, so only the IR build
        # imports it, never the domain's traversal.
        rules = tmp_path / "rules"
        _write_module(rules, "noisy_lint_rule_2103", _LINT_RULE)
        extra = ("--right", str(ir_file)) if args[:2] == ("ir", "diff") else ()

        result = _run_protean(
            tmp_path, *args, *extra, "--domain", str(module), pythonpath=rules
        )

        _assert_a_result_payload(result)
        assert "LINTIMPORT" not in result.stdout
        assert "LINTRUN" not in result.stdout
        assert "LINTRUN" in result.stderr
