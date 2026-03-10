"""Tests for the shared IR loading utilities in protean.cli._ir_utils."""

import json

import pytest
from click.exceptions import Abort

from protean.cli._ir_utils import load_ir_file


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

    def test_invalid_json_aborts(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(Abort):
            load_ir_file(str(path))
