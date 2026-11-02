"""Test cases for domain loading from various sources"""

import os
import sys
from pathlib import Path

import pytest

from protean import Domain
from protean.cli import NoDomainException
from protean.utils.domain_discovery import (
    derive_domain,
    find_domain_in_module,
    locate_domain,
    prepare_import,
)
from tests.shared import change_working_directory_to


def test_find_domain_in_module():
    class Module:
        domain = Domain(name="name")

    assert find_domain_in_module(Module) == Module.domain

    class Module:
        subdomain = Domain(name="name")

    assert find_domain_in_module(Module) == Module.subdomain

    class Module:
        my_domain = Domain(name="name")

    assert find_domain_in_module(Module) == Module.my_domain

    class Module:
        pass

    with pytest.raises(NoDomainException):
        find_domain_in_module(Module)

    class Module:
        my_domain1 = Domain(name="name1")
        my_domain2 = Domain(name="name2")

    with pytest.raises(NoDomainException):
        find_domain_in_module(Module)

    class Module:
        foo = "bar"

    with pytest.raises(NoDomainException):
        find_domain_in_module(Module)


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


class TestPrepareImport:
    @pytest.fixture(autouse=True)
    def restore_sys_path(self, monkeypatch):
        """`prepare_import` inserts the module's parent folder into `sys.path`."""
        monkeypatch.setattr(sys, "path", [*sys.path])

    def test_current_directory_resolves_to_domain_module(self, tmp_path, monkeypatch):
        """Given ".", `prepare_import` returns `domain` when the folder has a
        `domain.py`."""
        (tmp_path / "domain.py").write_text("# domain file\n")
        monkeypatch.chdir(tmp_path)

        assert prepare_import(".") == "domain"

    def test_current_directory_resolves_to_subdomain_module(
        self, tmp_path, monkeypatch
    ):
        """Given ".", `prepare_import` returns `subdomain` when the folder has a
        `subdomain.py` and no `domain.py`."""
        (tmp_path / "subdomain.py").write_text("# subdomain file\n")
        monkeypatch.chdir(tmp_path)

        assert prepare_import(".") == "subdomain"

    def test_package_init_file_resolves_to_package_name(self, tmp_path):
        """A path to a package's `__init__.py` resolves to the package name."""
        package_dir = tmp_path / "mypackage"
        package_dir.mkdir()
        init_file = package_dir / "__init__.py"
        init_file.write_text("# init file\n")

        assert prepare_import(str(init_file)) == "mypackage"


class TestLocateDomain:
    def test_import_error_inside_module_raises_no_domain_exception(
        self, tmp_path, monkeypatch
    ):
        """An ImportError raised by the module's own imports is reported as a
        `NoDomainException` that names the module and includes the traceback."""
        (tmp_path / "nested_error_module.py").write_text(
            "import nonexistent_dependency\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.delitem(sys.modules, "nested_error_module", raising=False)

        with pytest.raises(NoDomainException) as exc_info:
            locate_domain("nested_error_module", None)

        message = str(exc_info.value)
        assert message.startswith(
            "While importing 'nested_error_module', an ImportError was raised:\n\n"
        )
        assert "No module named 'nonexistent_dependency'" in message

    def test_missing_module_returns_none_when_not_required(self):
        """A module that does not exist yields None when `raise_if_not_found`
        is False."""
        result = locate_domain(
            "definitely_nonexistent_module_12345", None, raise_if_not_found=False
        )

        assert result is None


class TestDeriveDomainWithoutPath:
    @pytest.fixture(autouse=True)
    def project_dir(self, tmp_path, monkeypatch):
        """Run each test in an empty folder with no `PROTEAN_DOMAIN` set, and
        forget any `domain` module the test imports."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        monkeypatch.setattr(sys, "path", [*sys.path])
        monkeypatch.delitem(sys.modules, "domain", raising=False)
        yield tmp_path
        sys.modules.pop("domain", None)

    def test_returns_domain_defined_in_domain_py(self, project_dir):
        """With no path and no `PROTEAN_DOMAIN`, `derive_domain` loads the
        domain from `domain.py` in the current folder."""
        (project_dir / "domain.py").write_text(
            "from protean import Domain\ndomain = Domain(name='Fallback')\n"
        )

        domain = derive_domain(None)

        assert isinstance(domain, Domain)
        assert domain.name == "Fallback"

    def test_returns_none_when_no_domain_py_exists(self):
        """With no path, no `PROTEAN_DOMAIN` and no `domain.py`, `derive_domain`
        returns None."""
        assert derive_domain(None) is None
