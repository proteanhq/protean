"""Tests for the shared IR loading utilities in protean.cli._ir_utils."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.exceptions import Abort

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
