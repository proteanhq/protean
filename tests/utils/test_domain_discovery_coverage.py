"""Test cases to cover uncovered lines in domain_discovery.py"""

import os
import sys
import tempfile
from unittest.mock import patch

import pytest

from protean import Domain
from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import (
    derive_domain,
    locate_domain,
    prepare_import,
)


class TestPrepareImport:
    """Test cases for prepare_import function"""

    def test_prepare_import_with_current_directory_domain_py(self):
        """Test for prepare_import with '.' path and domain.py exists"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create domain.py in the temp directory
            domain_file = os.path.join(temp_dir, "domain.py")
            with open(domain_file, "w") as f:
                f.write("# domain file")

            # Change to temp directory
            old_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                result = prepare_import(".")
                assert result == "domain"
            finally:
                os.chdir(old_cwd)

    def test_prepare_import_with_current_directory_subdomain_py(self):
        """Test for prepare_import with '.' path and subdomain.py exists"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create subdomain.py in the temp directory
            subdomain_file = os.path.join(temp_dir, "subdomain.py")
            with open(subdomain_file, "w") as f:
                f.write("# subdomain file")

            # Change to temp directory
            old_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                result = prepare_import(".")
                assert result == "subdomain"
            finally:
                os.chdir(old_cwd)

    def test_prepare_import_with_init_basename(self):
        """Test for prepare_import with __init__ basename"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create package structure
            package_dir = os.path.join(temp_dir, "mypackage")
            os.makedirs(package_dir)
            init_file = os.path.join(package_dir, "__init__.py")
            with open(init_file, "w") as f:
                f.write("# init file")

            # Test with __init__.py path
            result = prepare_import(init_file)
            assert result == "mypackage"


class TestLocateDomain:
    """Test cases for locate_domain function"""

    def test_locate_domain_with_nested_import_error(self):
        """Test for locate_domain with nested ImportError"""
        # Create a temporary module that will fail during import with a nested error
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a Python file that imports another non-existent module
            nested_module_path = os.path.join(temp_dir, "nested_error_module.py")
            with open(nested_module_path, "w") as f:
                f.write("import nonexistent_dependency\n")

            # Add the temp directory to sys.path so Python can find the module
            original_path = sys.path[:]
            sys.path.insert(0, temp_dir)

            try:
                with pytest.raises(NoDomainException) as exc_info:
                    locate_domain("nested_error_module", None)

                assert "While importing" in str(exc_info.value)
                assert "an ImportError was raised" in str(exc_info.value)
            finally:
                # Clean up
                sys.path[:] = original_path
                # Remove the module from sys.modules if it was added
                if "nested_error_module" in sys.modules:
                    del sys.modules["nested_error_module"]

    def test_locate_domain_with_raise_if_not_found_false(self):
        """Test for locate_domain with raise_if_not_found=False"""
        # Test with a module that doesn't exist - this should trigger the simple ImportError case
        result = locate_domain(
            "definitely_nonexistent_module_12345", None, raise_if_not_found=False
        )
        assert result is None


class TestDeriveDomain:
    """Test cases for derive_domain function"""

    def test_derive_domain_fallback_to_domain_py(self):
        """Test for derive_domain fallback case"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create domain.py in the temp directory
            domain_file = os.path.join(temp_dir, "domain.py")
            with open(domain_file, "w") as f:
                f.write("from protean import Domain\ndomain = Domain()\n")

            # Change to temp directory and clear environment
            old_cwd = os.getcwd()
            old_env = os.environ.get("PROTEAN_DOMAIN")
            try:
                os.chdir(temp_dir)
                if old_env:
                    del os.environ["PROTEAN_DOMAIN"]

                # Mock locate_domain to return None for the fallback case
                with patch(
                    "protean.utils.domain_discovery.locate_domain"
                ) as mock_locate:
                    mock_locate.return_value = None

                    result = derive_domain(None)
                    assert result is None

                    # Verify locate_domain was called with expected parameters
                    assert mock_locate.call_count == 1
                    call_args = mock_locate.call_args
                    assert call_args[0][0] == "domain"  # import_name
                    assert call_args[0][1] is None  # name
                    assert call_args[1]["raise_if_not_found"] is False

            finally:
                os.chdir(old_cwd)
                if old_env:
                    os.environ["PROTEAN_DOMAIN"] = old_env

    def test_derive_domain_with_no_domain_import_path(self):
        """Test when no domain_import_path is provided"""
        old_env = os.environ.get("PROTEAN_DOMAIN")
        try:
            # Clear environment variable
            if old_env:
                del os.environ["PROTEAN_DOMAIN"]

            with patch("protean.utils.domain_discovery.prepare_import") as mock_prepare:
                with patch(
                    "protean.utils.domain_discovery.locate_domain"
                ) as mock_locate:
                    mock_prepare.return_value = "domain"
                    mock_locate.return_value = Domain()

                    # Call derive_domain with None to trigger the else branch
                    result = derive_domain(None)

                    # Verify the fallback behavior
                    mock_prepare.assert_called_with("domain.py")
                    mock_locate.assert_called_with(
                        "domain", None, raise_if_not_found=False
                    )
                    assert isinstance(result, Domain)

        finally:
            if old_env:
                os.environ["PROTEAN_DOMAIN"] = old_env
