import os
import sys

from pathlib import Path

import pytest

from protean.utils.domain_discovery import derive_domain
from tests.shared import change_working_directory_to


class TestDomainName:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_domain_with_explicit_name(self):
        change_working_directory_to("test10")

        domain = derive_domain("domain")
        assert domain is not None
        assert domain.name == "TEST10"

    def test_domain_with_implicit_name(self):
        change_working_directory_to("test13")

        domain = derive_domain("publishing13")
        assert domain is not None
        assert domain.name == "publishing13"
