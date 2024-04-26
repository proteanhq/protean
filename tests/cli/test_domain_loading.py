"""Test cases for domain loading from various sources"""

import os
import sys

from pathlib import Path

import pytest

from protean import Domain
from protean.cli import NoDomainException
from protean.utils.domain_discovery import derive_domain, find_domain_in_module
from tests.shared import change_working_directory_to


def test_find_domain_in_module():
    class Module:
        domain = Domain(__file__, "name")

    assert find_domain_in_module(Module) == Module.domain

    class Module:
        subdomain = Domain(__file__, "name")

    assert find_domain_in_module(Module) == Module.subdomain

    class Module:
        my_domain = Domain(__file__, "name")

    assert find_domain_in_module(Module) == Module.my_domain

    class Module:
        pass

    pytest.raises(NoDomainException, find_domain_in_module, Module)

    class Module:
        my_domain1 = Domain(__file__, "name1")
        my_domain2 = Domain(__file__, "name2")

    pytest.raises(NoDomainException, find_domain_in_module, Module)

    class Module:
        foo = "bar"

    pytest.raises(NoDomainException, find_domain_in_module, Module)


class TestDomainLoading:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_loading_domain_named_as_domain(self):
        change_working_directory_to("test1")

        domain = derive_domain("basic")
        assert domain is not None
        assert domain.name == "BASIC"

    def test_loading_domain_under_directory(self):
        change_working_directory_to("test2")

        domain = derive_domain("src/folder")
        assert domain is not None
        assert domain.name == "FOLDER"

    def test_loading_domain_from_module(self):
        change_working_directory_to("test3")

        domain = derive_domain("nested.web")
        assert domain is not None
        assert domain.name == "WEB"

    def test_loading_domain_from_instance(self):
        change_working_directory_to("test4")

        domain = derive_domain("instance:dom2")
        assert domain is not None
        assert domain.name == "INSTANCE"

    def test_loading_domain_from_invalid_module(self):
        change_working_directory_to("test5")

        with pytest.raises(NoDomainException):
            derive_domain("dummy")

    def test_loading_domain_with_attribute_name_as_domain(self):
        change_working_directory_to("test1")

        domain = derive_domain("basic")
        assert domain is not None
        assert domain.name == "BASIC"

    def test_loading_domain_with_attribute_name_as_subdomain(self):
        change_working_directory_to("test12")

        domain = derive_domain("foo12")
        assert domain is not None
        assert domain.name == "TEST12"
