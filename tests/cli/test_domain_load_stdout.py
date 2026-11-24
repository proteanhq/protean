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


def _run_protean(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PROTEAN_DOMAIN"}
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
            extra = ("--dir", str(protean_dir))

        result = _run_protean(tmp_path, *args, *extra, "--domain", str(module))

        assert json.loads(result.stdout), result.stderr
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
