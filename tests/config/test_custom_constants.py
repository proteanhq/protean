"""Tests to load domain configuration from .toml file"""

import os
import sys
from pathlib import Path

import pytest

from protean import Domain
from protean.utils.domain_discovery import derive_domain
from tests.shared import change_working_directory_to


class TestConstantsOnDomain:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_constants_on_domain(self):
        change_working_directory_to("test14")

        domain = derive_domain("domain14")
        assert domain is not None
        domain.FOO == "bar"

    def test_when_no_constants_are_defined(self):
        domain = Domain()
        assert domain is not None
        assert hasattr(domain, "FOO") is False
