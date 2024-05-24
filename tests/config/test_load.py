"""Tests to load domain configuration from .toml file"""

import os
import sys

from pathlib import Path

import pytest

from protean.utils.domain_discovery import derive_domain
from tests.shared import change_working_directory_to


class TestLoadingTOML:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    @pytest.mark.no_test_domain
    def test_domain_detects_config_file(self):
        change_working_directory_to("test14")

        domain = derive_domain("domain14")
        assert domain is not None
        domain.config["CUSTOM"]["FOO"] == "bar"

    @pytest.mark.skip(reason="No Immutability Functionality yet")
    def test_domain_config_is_immutable(self):
        change_working_directory_to("test14")

        domain = derive_domain("domain14")
        with pytest.raises(TypeError):
            domain.config["CUSTOM"]["FOO"] = "baz"

    @pytest.mark.no_test_domain
    def test_domain_prioritizes_dot_domain_toml_over_domain_toml(self):
        """Ensure protean tries to parse configuration from files in the following order:

        1. .domain.toml
        2. domain.toml
        3. pyproject.toml
        """
        change_working_directory_to("test15")

        domain = derive_domain("domain15")
        assert domain is not None
        assert domain.config["CUSTOM"]["FOO"] == "baz"

    @pytest.mark.no_test_domain
    def test_domain_prioritizes_domain_toml_over_pyproject(self):
        """Ensure protean tries to parse configuration from files in the following order:

        1. .domain.toml
        2. domain.toml
        3. pyproject.toml
        """
        change_working_directory_to("test16")

        domain = derive_domain("domain16")
        assert domain is not None
        assert domain.config["CUSTOM"]["FOO"] == "qux"

    @pytest.mark.no_test_domain
    def test_domain_picks_pyproject_toml_in_the_absence_of_other_config_files(self):
        """Ensure protean tries to parse configuration from files in the following order:

        1. .domain.toml
        2. domain.toml
        3. pyproject.toml
        """
        change_working_directory_to("test17")

        domain = derive_domain("domain17")
        assert domain is not None
        assert domain.config["CUSTOM"]["FOO"] == "quux"

    @pytest.mark.skip(reason="No Immutability Functionality yet")
    def test_custom_is_immutable(self):
        change_working_directory_to("test14")

        domain = derive_domain("domain14")
        with pytest.raises(TypeError):
            domain.config["CUSTOM"]["FOO"] = "baz"

    @pytest.mark.no_test_domain
    def test_domain_loads_config_successfully(self):
        pass

    @pytest.mark.no_test_domain
    def test_domain_throws_error_if_config_file_not_found(self):
        pass
