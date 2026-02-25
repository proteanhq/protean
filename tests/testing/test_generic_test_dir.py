"""Tests for the get_generic_test_dir() helper in protean.testing."""

from pathlib import Path
from unittest.mock import patch

import pytest

from protean.testing import get_generic_test_dir


class TestGetGenericTestDir:
    """Test get_generic_test_dir() function."""

    def test_returns_path_when_directory_exists(self):
        """Test it returns a valid Path when the generic test dir exists."""
        result = get_generic_test_dir()
        assert isinstance(result, Path)
        assert result.is_dir()
        assert result.name == "generic"

    def test_returned_path_contains_test_files(self):
        """Test the returned directory actually contains test files."""
        result = get_generic_test_dir()
        test_files = list(result.glob("test_*.py"))
        assert len(test_files) > 0

    def test_returned_path_contains_conftest(self):
        """Test the returned directory contains a conftest.py."""
        result = get_generic_test_dir()
        assert (result / "conftest.py").is_file()

    def test_raises_when_directory_not_found(self):
        """Test it raises FileNotFoundError when directory doesn't exist."""
        with patch.object(Path, "is_dir", return_value=False):
            with pytest.raises(FileNotFoundError, match="conformance tests not found"):
                get_generic_test_dir()
