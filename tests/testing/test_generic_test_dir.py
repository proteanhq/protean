"""Tests for the get_generic_test_dir() helper in protean.testing."""

import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

from protean._deprecation import RemovedInProtean020Warning
from protean.testing import get_generic_test_dir

REPO_ROOT = Path(__file__).resolve().parents[2]


def generic_test_dir() -> Path:
    """Call ``get_generic_test_dir()`` with its deprecation warning silenced."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RemovedInProtean020Warning)
        return get_generic_test_dir()


class TestGetGenericTestDir:
    """Test get_generic_test_dir() function."""

    def test_returns_path_when_directory_exists(self):
        """Test it returns a valid Path when the generic test dir exists."""
        result = generic_test_dir()
        assert isinstance(result, Path)
        assert result.is_dir()
        assert result.name == "generic"

    def test_returns_the_database_suite_folder(self):
        assert generic_test_dir() == REPO_ROOT / "tests/adapters/repository/generic"

    def test_returned_path_contains_test_files(self):
        """Test the returned directory actually contains test files."""
        result = generic_test_dir()
        test_files = list(result.glob("test_*.py"))
        assert len(test_files) > 0

    def test_returned_path_contains_conftest(self):
        """Test the returned directory contains a conftest.py."""
        result = generic_test_dir()
        assert (result / "conftest.py").is_file()

    def test_raises_when_directory_not_found(self):
        """Test it raises FileNotFoundError when directory doesn't exist."""
        with patch.object(Path, "is_dir", return_value=False):
            with pytest.raises(FileNotFoundError, match="conformance tests not found"):
                generic_test_dir()


class TestDeprecation:
    def test_each_call_warns_once_naming_the_removal_version(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            get_generic_test_dir()

        assert len(caught) == 1
        assert caught[0].category is RemovedInProtean020Warning
        message = str(caught[0].message)
        assert message.startswith(
            "protean.testing.get_generic_test_dir() is deprecated."
        )
        assert "protean test test-adapter --port database" in message
        assert message.endswith("Will be removed in v0.20.0.")

    def test_the_warning_points_at_the_caller(self):
        with pytest.warns(RemovedInProtean020Warning) as caught:
            get_generic_test_dir()

        assert caught[0].filename == __file__
