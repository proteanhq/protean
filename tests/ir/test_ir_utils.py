"""Tests for the shared IR loading utilities in protean.cli._ir_utils."""

import json
import os
import sys
from unittest.mock import patch

import pytest
from typer import Abort, Exit

from protean.cli._ir_utils import load_domain_ir, load_ir_file

_GOOD_DOMAIN = """
from protean import Domain
from protean.fields import String

domain = Domain(name="IRUtilsGood")


@domain.aggregate
class Order:
    name = String()
"""

# An entity that names a missing aggregate fails when the domain initialises.
_INIT_FAILS_DOMAIN = """
from protean import Domain
from protean.fields import String

domain = Domain(name="IRUtilsInitFails")


@domain.entity(part_of="Missing")
class Line:
    name = String()
"""

_IMPORT_RAISES_DOMAIN = 'raise RuntimeError("boom at import")\n'

_SYNTAX_ERROR_DOMAIN = "def broken(:\n"


@pytest.fixture
def domain_dir(tmp_path, monkeypatch):
    """Return a function that writes a domain module into a working folder.

    The function takes a module name and its source and returns the path
    ``load_domain_ir`` accepts. The folder is the working directory and on
    ``sys.path``; the written modules leave ``sys.modules`` afterwards.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    written: list[str] = []

    def write(name: str, source: str) -> str:
        (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
        written.append(name)
        return f"{name}.py"

    yield write
    for name in written:
        sys.modules.pop(name, None)


def _one_line(text: str) -> str:
    # Rich wraps output to the terminal width; join the words back up.
    return " ".join(text.split())


class TestLoadIrFile:
    """Tests for load_ir_file — loading IR from a JSON file."""

    def test_loads_valid_json(self, tmp_path):
        ir = {"ir_version": "0.1.0", "clusters": {}}
        path = tmp_path / "test.json"
        path.write_text(json.dumps(ir), encoding="utf-8")

        result = load_ir_file(str(path))
        assert result == ir

    def test_directory_path_aborts(self, tmp_path):
        with pytest.raises(Abort):
            load_ir_file(str(tmp_path))

    def test_invalid_json_aborts(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(Abort):
            load_ir_file(str(path))


class TestLoadDomainIr:
    """Tests for load_domain_ir: building IR from a live domain."""

    def test_returns_ir_dict(self, domain_dir):
        result = load_domain_ir(domain_dir("ir_utils_good_domain", _GOOD_DOMAIN))

        assert result["domain"]["name"] == "IRUtilsGood"
        assert result["elements"]["AGGREGATE"] == ["ir_utils_good_domain.Order"]

    def test_no_domain_aborts(self, domain_dir, capsys):
        with pytest.raises(Abort):
            load_domain_ir("no_such_ir_utils_module.py")
        assert (
            "Error loading Protean domain: Could not import 'no_such_ir_utils_module'."
            in _one_line(capsys.readouterr().out)
        )

    def test_init_error_aborts(self, domain_dir, capsys):
        path = domain_dir("ir_utils_init_fails_domain", _INIT_FAILS_DOMAIN)
        with pytest.raises(Abort):
            load_domain_ir(path)
        out = _one_line(capsys.readouterr().out)
        assert "Error initialising Protean domain:" in out
        assert "Unresolved references" in out


class TestUsageExit:
    """``usage_exit=True`` reports a load failure on stderr and exits 2;
    the default keeps the stdout line and the exit-1 ``Abort``."""

    def test_default_prints_to_stdout_and_aborts(self, tmp_path, capsys):
        with pytest.raises(Abort):
            load_ir_file(str(tmp_path / "missing.json"))
        captured = capsys.readouterr()
        assert "file not found or not a regular file" in captured.out
        assert captured.err == ""

    def test_missing_file_exits_2_on_stderr(self, tmp_path, capsys):
        with pytest.raises(Exit) as exc_info:
            load_ir_file(str(tmp_path / "missing.json"), usage_exit=True)
        assert exc_info.value.exit_code == 2
        captured = capsys.readouterr()
        assert "Error: file not found or not a regular file" in captured.err
        assert captured.out == ""

    def test_invalid_json_exits_2_on_stderr(self, tmp_path, capsys):
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(Exit) as exc_info:
            load_ir_file(str(path), usage_exit=True)
        assert exc_info.value.exit_code == 2
        assert "invalid JSON in" in capsys.readouterr().err

    def test_non_object_json_exits_2_on_stderr(self, tmp_path, capsys):
        path = tmp_path / "list.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(Exit) as exc_info:
            load_ir_file(str(path), usage_exit=True)
        assert exc_info.value.exit_code == 2
        assert "IR file is not a JSON object" in capsys.readouterr().err

    def test_domain_not_found_exits_2_on_stderr(self, domain_dir, capsys):
        with pytest.raises(Exit) as exc_info:
            load_domain_ir("no_such_ir_utils_module.py", usage_exit=True)
        assert exc_info.value.exit_code == 2
        captured = capsys.readouterr()
        assert (
            "Error loading Protean domain: Could not import 'no_such_ir_utils_module'."
            in _one_line(captured.err)
        )
        assert captured.out == ""

    def test_domain_init_error_exits_2_on_stderr(self, domain_dir, capsys):
        path = domain_dir("ir_utils_init_fails_domain", _INIT_FAILS_DOMAIN)
        with pytest.raises(Exit) as exc_info:
            load_domain_ir(path, usage_exit=True)
        assert exc_info.value.exit_code == 2
        err = _one_line(capsys.readouterr().err)
        assert "Error initialising Protean domain:" in err
        assert "`Line` references `Missing` via part_of" in err

    def test_to_ir_error_exits_2_on_stderr(self, domain_dir, tmp_path, capsys):
        # A lint table with a non-list ``rules`` loads and initialises, then
        # fails when the IR is built.
        (tmp_path / "domain.toml").write_text("[lint]\nrules = 5\n")
        path = domain_dir("ir_utils_bad_lint_domain", _GOOD_DOMAIN)
        with pytest.raises(Exit) as exc_info:
            load_domain_ir(path, usage_exit=True)
        assert exc_info.value.exit_code == 2
        assert (
            "Error generating IR from Protean domain: [lint].rules must be a list"
            in _one_line(capsys.readouterr().err)
        )

    def test_domain_import_error_exits_2_on_stderr(self, domain_dir, capsys):
        path = domain_dir("ir_utils_import_raises_domain", _IMPORT_RAISES_DOMAIN)
        with pytest.raises(Exit) as exc_info:
            load_domain_ir(path, usage_exit=True)
        assert exc_info.value.exit_code == 2
        assert "Error loading Protean domain: RuntimeError: boom at import" in (
            _one_line(capsys.readouterr().err)
        )

    def test_domain_import_error_aborts_by_default(self, domain_dir, capsys):
        path = domain_dir("ir_utils_syntax_error_domain", _SYNTAX_ERROR_DOMAIN)
        with pytest.raises(Abort):
            load_domain_ir(path)
        assert "Error loading Protean domain: SyntaxError:" in (
            _one_line(capsys.readouterr().out)
        )

    def test_non_utf8_file_exits_2_on_stderr(self, tmp_path, capsys):
        path = tmp_path / "binary.json"
        path.write_bytes(b"\xff\xfe")
        with pytest.raises(Exit) as exc_info:
            load_ir_file(str(path), usage_exit=True)
        assert exc_info.value.exit_code == 2
        # Rich wraps stderr to the terminal width, so compare without spaces.
        err = "".join(capsys.readouterr().err.split())
        assert f"couldnotread{path}" in err

    @pytest.mark.skipif(
        sys.platform == "win32" or os.geteuid() == 0,
        reason="file permissions do not block reads on Windows or as root",
    )
    def test_unreadable_file_exits_2_on_stderr(self, tmp_path, capsys):
        path = tmp_path / "locked.json"
        path.write_text("{}", encoding="utf-8")
        path.chmod(0)
        try:
            with pytest.raises(Exit) as exc_info:
                load_ir_file(str(path), usage_exit=True)
        finally:
            path.chmod(0o600)
        assert exc_info.value.exit_code == 2
        err = "".join(capsys.readouterr().err.split())
        assert f"couldnotread{path}" in err
        assert "Permissiondenied" in err

    def test_unsearchable_parent_exits_2_on_stderr(self, tmp_path, capsys):
        # Before Python 3.14, is_file() raises PermissionError when a parent
        # directory is not searchable; simulate it so every version runs this.
        path = tmp_path / "locked" / "ir.json"
        with patch(
            "pathlib.Path.is_file", side_effect=PermissionError("Permission denied")
        ):
            with pytest.raises(Exit) as exc_info:
                load_ir_file(str(path), usage_exit=True)
        assert exc_info.value.exit_code == 2
        err = "".join(capsys.readouterr().err.split())
        assert f"couldnotread{path}" in err
        assert "Permissiondenied" in err

    def test_as_json_wins_over_usage_exit(self, domain_dir, capsys):
        with pytest.raises(Exit) as exc_info:
            load_domain_ir("no_such_ir_utils_module.py", as_json=True, usage_exit=True)
        assert exc_info.value.exit_code == 2
        captured = capsys.readouterr()
        assert '"status": "error"' in captured.out
        assert captured.err == ""
