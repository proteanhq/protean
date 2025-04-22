import os
import sys
from pathlib import Path

import pytest

from protean.utils.domain_discovery import derive_domain
from tests.shared import change_working_directory_to


class TestDomainTraversal:
    @pytest.mark.no_test_domain
    def test_loading_domain_without_init(self):
        from tests.support.domains.test6 import publishing6

        assert publishing6.domain is not None
        assert len(publishing6.domain.registry.aggregates) == 0

    @pytest.mark.no_test_domain
    def test_loading_domain_with_init(self):
        from tests.support.domains.test7 import publishing7

        assert publishing7.domain is not None
        publishing7.domain.init()
        assert (
            len(publishing7.domain.registry.aggregates) == 2
        )  # Includes MemoryMessage Aggregate

    @pytest.mark.no_test_domain
    def test_loading_nested_domain_with_init(self):
        from tests.support.domains.test13 import publishing13

        assert publishing13.domain is not None
        publishing13.domain.init()
        assert (
            len(publishing13.domain.registry.aggregates) == 3
        )  # Includes MemoryMessage Aggregate


@pytest.mark.no_test_domain
class TestMultiFolderStructureTraversal:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_all_elements_in_nested_structure_are_registered(self):
        change_working_directory_to("test20")

        domain = derive_domain("publishing20:publishing")
        assert domain is not None
        assert domain.name == "Publishing20"

        domain.init()
        assert len(domain.registry.aggregates) == 3  # Includes MemoryMessage Aggregate

    def test_elements_in_folder_with_their_own_toml_are_ignored(self):
        change_working_directory_to("test21")

        domain = derive_domain("publishing21:publishing")
        assert domain is not None
        assert domain.name == "Publishing21"

        domain.init()
        assert len(domain.registry.aggregates) == 2  # Includes MemoryMessage Aggregate


@pytest.mark.no_test_domain
def test_is_domain_file_nonexistent_path():
    """Test that _is_domain_file returns False for non-existent paths."""
    from protean import Domain

    domain = Domain()

    # Test with a non-existent file path
    non_existent_path = "/path/that/definitely/does/not/exist.py"

    # This should return False since the path doesn't exist
    result = domain._is_domain_file(non_existent_path)
    assert result is False


@pytest.mark.no_test_domain
def test_traverse_with_file_path():
    """Test that _traverse correctly handles when root_path is a file path."""
    import tempfile
    from unittest.mock import MagicMock, patch

    from protean import Domain

    # Create a temporary file to use as the root_path
    with tempfile.NamedTemporaryFile(suffix=".py") as temp_file:
        # Create a Domain with the temporary file path as root_path
        domain = Domain(root_path=temp_file.name)

        # Verify the root_path is a file
        assert Path(domain.root_path).is_file()

        # We'll patch the actual traversal logic to avoid side effects
        with patch("os.listdir") as mock_listdir, patch(
            "importlib.util.spec_from_file_location"
        ) as mock_spec:
            # Configure mocks to prevent actual traversal
            mock_listdir.return_value = []

            # Call _traverse directly
            domain._traverse()

            # The key assertion: verify that mock_listdir was called with the parent directory
            # This confirms that when root_path is a file, the code correctly uses the parent dir
            parent_dir = str(Path(temp_file.name).parent)
            mock_listdir.assert_called_with(parent_dir)
