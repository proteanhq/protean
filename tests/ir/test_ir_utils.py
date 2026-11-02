"""Tests for the shared IR loading utilities in protean.cli._ir_utils."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from typer import Abort, Exit

from protean.cli._ir_utils import load_domain_ir, load_ir_file
from protean.exceptions import NoDomainException


class TestLoadIrFile:
    """Tests for load_ir_file — loading IR from a JSON file."""

    def test_loads_valid_json(self, tmp_path):
        ir = {"ir_version": "0.1.0", "clusters": {}}
        path = tmp_path / "test.json"
        path.write_text(json.dumps(ir), encoding="utf-8")

        result = load_ir_file(str(path))
        assert result == ir

    def test_file_not_found_aborts(self, tmp_path):
        missing = str(tmp_path / "missing.json")
        with pytest.raises(Abort):
            load_ir_file(missing)

    def test_directory_path_aborts(self, tmp_path):
        with pytest.raises(Abort):
            load_ir_file(str(tmp_path))

    def test_invalid_json_aborts(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(Abort):
            load_ir_file(str(path))


class TestLoadDomainIr:
    """Tests for load_domain_ir — building IR from a live domain."""

    @patch("protean.cli._ir_utils.derive_domain")
    def test_returns_ir_dict(self, mock_derive):
        expected_ir = {"ir_version": "0.1.0", "clusters": {}}
        mock_domain = MagicMock()
        mock_domain.to_ir.return_value = expected_ir
        mock_derive.return_value = mock_domain

        result = load_domain_ir("my_app.domain")

        mock_derive.assert_called_once_with("my_app.domain")
        mock_domain.init.assert_called_once()
        mock_domain.to_ir.assert_called_once()
        assert result == expected_ir

    @patch("protean.cli._ir_utils.derive_domain")
    def test_no_domain_aborts(self, mock_derive):
        mock_derive.side_effect = NoDomainException("not found")
        with pytest.raises(Abort):
            load_domain_ir("bad_path")

    @patch("protean.cli._ir_utils.derive_domain")
    def test_init_error_aborts(self, mock_derive):
        mock_domain = MagicMock()
        mock_domain.init.side_effect = RuntimeError("init failed")
        mock_derive.return_value = mock_domain

        with pytest.raises(Abort):
            load_domain_ir("my_app.domain")


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

    @patch("protean.cli._ir_utils.derive_domain")
    def test_domain_not_found_exits_2_on_stderr(self, mock_derive, capsys):
        mock_derive.side_effect = NoDomainException("not found")
        with pytest.raises(Exit) as exc_info:
            load_domain_ir("bad_path", usage_exit=True)
        assert exc_info.value.exit_code == 2
        assert "Error loading Protean domain: not found" in capsys.readouterr().err

    @patch("protean.cli._ir_utils.derive_domain")
    def test_domain_init_error_exits_2_on_stderr(self, mock_derive, capsys):
        mock_domain = MagicMock()
        mock_domain.init.side_effect = RuntimeError("init failed")
        mock_derive.return_value = mock_domain
        with pytest.raises(Exit) as exc_info:
            load_domain_ir("my_app.domain", usage_exit=True)
        assert exc_info.value.exit_code == 2
        assert "Error initialising Protean domain: init failed" in (
            capsys.readouterr().err
        )

    @patch("protean.cli._ir_utils.derive_domain")
    def test_to_ir_error_exits_2_on_stderr(self, mock_derive, capsys):
        mock_domain = MagicMock()
        mock_domain.to_ir.side_effect = RuntimeError("to_ir failed")
        mock_derive.return_value = mock_domain
        with pytest.raises(Exit) as exc_info:
            load_domain_ir("my_app.domain", usage_exit=True)
        assert exc_info.value.exit_code == 2
        assert "Error generating IR from Protean domain: to_ir failed" in (
            capsys.readouterr().err
        )

    @patch("protean.cli._ir_utils.derive_domain")
    def test_domain_import_error_exits_2_on_stderr(self, mock_derive, capsys):
        mock_derive.side_effect = RuntimeError("boom at import")
        with pytest.raises(Exit) as exc_info:
            load_domain_ir("my_app.domain", usage_exit=True)
        assert exc_info.value.exit_code == 2
        assert "Error loading Protean domain: RuntimeError: boom at import" in (
            capsys.readouterr().err
        )

    @patch("protean.cli._ir_utils.derive_domain")
    def test_domain_import_error_aborts_by_default(self, mock_derive, capsys):
        mock_derive.side_effect = SyntaxError("bad syntax")
        with pytest.raises(Abort):
            load_domain_ir("my_app.domain")
        assert "Error loading Protean domain: SyntaxError: bad syntax" in (
            capsys.readouterr().out
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

    @patch("protean.cli._ir_utils.derive_domain")
    def test_as_json_wins_over_usage_exit(self, mock_derive, capsys):
        mock_derive.side_effect = NoDomainException("not found")
        with pytest.raises(Exit) as exc_info:
            load_domain_ir("bad_path", as_json=True, usage_exit=True)
        assert exc_info.value.exit_code == 2
        captured = capsys.readouterr()
        assert '"status": "error"' in captured.out
        assert captured.err == ""
