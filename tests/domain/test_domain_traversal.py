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
        assert len(publishing7.domain.registry.aggregates) == 1

    @pytest.mark.no_test_domain
    def test_loading_nested_domain_with_init(self):
        from tests.support.domains.test13 import publishing13

        assert publishing13.domain is not None
        publishing13.domain.init()
        assert len(publishing13.domain.registry.aggregates) == 2


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
        assert len(domain.registry.aggregates) == 2

    def test_elements_in_folder_with_their_own_toml_are_ignored(self):
        change_working_directory_to("test21")

        domain = derive_domain("publishing21:publishing")
        assert domain is not None
        assert domain.name == "Publishing21"

        domain.init()
        assert len(domain.registry.aggregates) == 1
