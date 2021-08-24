import os
import sys

from pathlib import Path

import pytest

from click.testing import CliRunner

from protean import Domain
from protean.cli import NoDomainException, derive_domain, find_best_domain


@pytest.fixture
def runner():
    return CliRunner()


def test_find_best_domain():
    class Module:
        domain = Domain("name")

    assert find_best_domain(Module) == Module.domain

    class Module:
        subdomain = Domain("name")

    assert find_best_domain(Module) == Module.subdomain

    class Module:
        my_domain = Domain("name")

    assert find_best_domain(Module) == Module.my_domain

    class Module:
        pass

    pytest.raises(NoDomainException, find_best_domain, Module)

    class Module:
        my_domain1 = Domain("name1")
        my_domain2 = Domain("name2")

    pytest.raises(NoDomainException, find_best_domain, Module)

    class Module:
        foo = "bar"

    pytest.raises(NoDomainException, find_best_domain, Module)


class TestDomainLoading:
    @pytest.fixture(autouse=True)
    def reset_path(self, request):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def change_working_directory_to(self, path):
        test_path = (
            Path(__file__) / ".." / "support" / "test_domains" / path
        ).resolve()

        os.chdir(test_path)
        sys.path.insert(0, test_path)

    def test_loading_domain_named_as_domain(self):
        self.change_working_directory_to("test1")

        domain = derive_domain("basic")
        assert domain is not None
        assert domain.domain_name == "BASIC"

    def test_loading_domain_under_directory(self):
        self.change_working_directory_to("test2")

        domain = derive_domain("src/folder")
        assert domain is not None
        assert domain.domain_name == "FOLDER"

    def test_loading_domain_from_module(self):
        self.change_working_directory_to("test3")

        domain = derive_domain("nested.web")
        assert domain is not None
        assert domain.domain_name == "WEB"

    def test_loading_domain_from_instance(self):
        self.change_working_directory_to("test4")

        domain = derive_domain("instance:dom2")
        assert domain is not None
        assert domain.domain_name == "INSTANCE"

    def test_loading_domain_from_invalid_module(self):
        self.change_working_directory_to("test5")

        with pytest.raises(NoDomainException):
            derive_domain("dummy")
