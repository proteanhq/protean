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
        """Give each test its own copy of `sys.path`, which `prepare_import` edits."""
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
        forget any `domain` or `subdomain` module the test imports."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        monkeypatch.setattr(sys, "path", [*sys.path])
        for module_name in ("domain", "subdomain"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
        yield tmp_path
        for module_name in ("domain", "subdomain"):
            sys.modules.pop(module_name, None)

    def test_returns_domain_defined_in_domain_py(self, project_dir):
        """With no path and no `PROTEAN_DOMAIN`, `derive_domain` loads the
        domain from `domain.py` in the current folder."""
        (project_dir / "domain.py").write_text(
            "from protean import Domain\ndomain = Domain(name='Fallback')\n"
        )

        domain = derive_domain(None)

        assert isinstance(domain, Domain)
        assert domain.name == "Fallback"

    def test_returns_domain_defined_in_subdomain_py(self, project_dir):
        """With no path and only `subdomain.py` in the current folder,
        `derive_domain` loads the domain from `subdomain.py`."""
        (project_dir / "subdomain.py").write_text(
            "from protean import Domain\nsubdomain = Domain(name='Sub')\n"
        )

        domain = derive_domain(None)

        assert isinstance(domain, Domain)
        assert domain.name == "Sub"

    def test_returns_none_when_no_domain_py_exists(self):
        """With no path, no `PROTEAN_DOMAIN` and no `domain.py`, `derive_domain`
        returns None."""
        assert derive_domain(None) is None


_DOMAIN_SOURCE = "from protean import Domain\ndomain = Domain(name={name!r})\n"


class TestDeriveDomainFromSrcLayout:
    """With no path, or the path ".", discovery falls back to `src/*/`."""

    @pytest.fixture(autouse=True)
    def project_dir(self, tmp_path, monkeypatch):
        """Run each test in an empty folder with no `PROTEAN_DOMAIN` set, and
        forget every module the test imports."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        monkeypatch.setattr(sys, "path", [*sys.path])
        yield tmp_path
        for module_name in list(sys.modules):
            if module_name.split(".")[0] in {
                "srcdemo",
                "srca",
                "srcb",
                "domain",
                "subdomain",
            }:
                sys.modules.pop(module_name)

    @staticmethod
    def _write_package(root: Path, package: str, filename: str, name: str) -> None:
        package_dir = root / "src" / package
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / filename).write_text(_DOMAIN_SOURCE.format(name=name))

    @pytest.mark.parametrize("domain_path", [".", None], ids=["dot", "no path"])
    def test_loads_the_one_domain_under_src(self, project_dir, domain_path):
        self._write_package(project_dir, "srcdemo", "domain.py", "Src")

        domain = derive_domain(domain_path)

        assert isinstance(domain, Domain)
        assert domain.name == "Src"
        assert sys.modules["srcdemo.domain"].domain is domain

    @pytest.mark.parametrize("domain_path", [".", None], ids=["dot", "no path"])
    def test_more_than_one_domain_under_src_is_an_error(self, project_dir, domain_path):
        self._write_package(project_dir, "srca", "domain.py", "A")
        self._write_package(project_dir, "srcb", "domain.py", "B")

        with pytest.raises(NoDomainException) as exc_info:
            derive_domain(domain_path)

        message = str(exc_info.value)
        assert os.path.join("src", "srca", "domain.py") in message
        assert os.path.join("src", "srcb", "domain.py") in message
        assert "--domain" in message

    def test_top_level_domain_wins_over_src(self, project_dir):
        (project_dir / "domain.py").write_text(_DOMAIN_SOURCE.format(name="Top"))
        self._write_package(project_dir, "srcdemo", "domain.py", "Src")

        domain = derive_domain(".")

        assert domain is not None
        assert domain.name == "Top"

    def test_loads_a_subdomain_under_src(self, project_dir):
        self._write_package(project_dir, "srcdemo", "subdomain.py", "Sub")

        domain = derive_domain(".")

        assert domain is not None
        assert domain.name == "Sub"

    def test_domain_under_src_wins_over_subdomain_under_src(self, project_dir):
        self._write_package(project_dir, "srca", "domain.py", "A")
        self._write_package(project_dir, "srcb", "subdomain.py", "B")

        domain = derive_domain(".")

        assert domain is not None
        assert domain.name == "A"

    def test_explicit_path_is_not_redirected_to_src(self, project_dir):
        self._write_package(project_dir, "srcdemo", "domain.py", "Src")

        with pytest.raises(NoDomainException, match="Could not import 'missing_pkg'"):
            derive_domain("missing_pkg")

    def test_empty_src_with_no_path_returns_none(self, project_dir):
        (project_dir / "src").mkdir()

        assert derive_domain(None) is None

    def test_prepare_import_puts_src_on_the_path(self, project_dir):
        self._write_package(project_dir, "srcdemo", "domain.py", "Src")

        assert prepare_import(".") == "srcdemo.domain"
        assert sys.path[0] == os.path.realpath(project_dir / "src")

    def test_top_level_domain_package_wins_over_src_with_no_path(self, project_dir):
        (project_dir / "domain").mkdir()
        (project_dir / "domain" / "__init__.py").write_text(
            _DOMAIN_SOURCE.format(name="Package")
        )
        self._write_package(project_dir, "srcdemo", "domain.py", "Src")

        domain = derive_domain(None)

        assert domain is not None
        assert domain.name == "Package"
