"""Tests to load domain configuration from .toml file"""

import os
import sys
from pathlib import Path

import pytest

from protean.domain.config import Config2
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

    def test_loading_domain_config(self, test_domain):
        assert test_domain is not None
        assert test_domain.config["databases"]["default"]["provider"] == "memory"
        assert all(
            key in test_domain.config["databases"] for key in ["default", "memory"]
        )
        assert all(
            key in test_domain.config
            for key in ["databases", "caches", "brokers", "event_store"]
        )

    @pytest.mark.no_test_domain
    def test_domain_detects_config_file(self):
        change_working_directory_to("test14")

        domain = derive_domain("domain14")
        assert domain is not None
        domain.config["custom"]["FOO"] == "bar"

    @pytest.mark.skip(reason="No Immutability Functionality yet")
    def test_domain_config_is_immutable(self):
        change_working_directory_to("test14")

        domain = derive_domain("domain14")
        with pytest.raises(TypeError):
            domain.config["custom"]["FOO"] = "baz"

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
        assert domain.config["custom"]["FOO"] == "baz"

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
        assert domain.config["custom"]["FOO"] == "qux"

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
        assert domain.config["custom"]["FOO"] == "quux"

    @pytest.mark.skip(reason="No Immutability Functionality yet")
    def test_custom_is_immutable(self):
        change_working_directory_to("test14")

        domain = derive_domain("domain14")
        with pytest.raises(TypeError):
            domain.config["custom"]["FOO"] = "baz"

    @pytest.mark.no_test_domain
    def test_warning_if_config_file_not_found(self):
        change_working_directory_to("test19")

        with pytest.warns(UserWarning, match="No configuration file found in"):
            derive_domain("domain19")


class TestLoadingDefaults:
    def test_that_config_is_loaded_from_dict(self):
        from protean.domain.config import _default_config

        config_dict = _default_config()
        config_dict["custom"] = {"FOO": "bar", "qux": "quux"}
        config = Config2.load_from_dict(config_dict)
        assert config["databases"]["default"]["provider"] == "memory"
        assert config["custom"]["FOO"] == "bar"
        assert config["custom"]["qux"] == "quux"


def test_that_config_is_loaded_from_1st_parent_folder_of_path():
    change_working_directory_to("test22")

    domain = derive_domain("src/publishing/domain22")
    assert domain.config["custom"]["foo"] == "corge"


def test_that_config_is_loaded_from_2nd_parent_folder_of_path():
    change_working_directory_to("test23")

    domain = derive_domain("src/publishing/domain23")
    assert domain.config["custom"]["foo"] == "grault"


def test_that_config_is_loaded_from_a_sub_context_in_pyproject_toml():
    change_working_directory_to("test24")

    domain = derive_domain("src/publishing/domain24")
    assert domain.config["custom"]["foo"] == "garply"
