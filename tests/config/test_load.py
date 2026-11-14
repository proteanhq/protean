"""Tests to load domain configuration from .toml file"""

import logging
import os
import sys
import warnings
from pathlib import Path

import pytest

from protean import Domain
from protean.domain.config import Config2, _find_config_file
from protean.utils.domain_discovery import derive_domain
from tests.shared import change_working_directory_to

NO_CONFIG_MESSAGE = "No configuration file found"


def _no_config_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "protean.domain.config"
        and NO_CONFIG_MESSAGE in record.getMessage()
    ]


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
        assert domain.config["custom"]["FOO"] == "bar"

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

    @pytest.mark.no_test_domain
    def test_no_warning_if_config_file_not_found(self):
        change_working_directory_to("test19")

        # Clean cached module so the Domain is freshly created
        sys.modules.pop("domain19", None)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            domain = derive_domain("domain19")

        assert _find_config_file(domain.root_path) is None
        assert domain.config["databases"]["default"]["provider"] == "memory"
        assert not [w for w in caught if NO_CONFIG_MESSAGE in str(w.message)]


@pytest.mark.no_test_domain
class TestDomainWithoutConfigFile:
    @pytest.fixture(autouse=True)
    def no_config_in_reach(self, tmp_path):
        # A config file in tmp_path or its 2 parents would make every test
        # here pass without exercising the no-config path.
        assert _find_config_file(str(tmp_path)) is None

    def test_construction_raises_no_warning(self, tmp_path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Domain(name="Test", root_path=str(tmp_path))

        assert not [w for w in caught if NO_CONFIG_MESSAGE in str(w.message)]

    def test_load_from_path_returns_defaults_without_warning(self, tmp_path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            config = Config2.load_from_path(str(tmp_path))

        assert config["databases"]["default"]["provider"] == "memory"
        assert not [w for w in caught if NO_CONFIG_MESSAGE in str(w.message)]

    def test_construction_logs_nothing(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG, logger="protean.domain.config")

        Domain(name="Test", root_path=str(tmp_path))

        assert _no_config_records(caplog) == []

    def test_init_logs_the_searched_directory_at_debug(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG, logger="protean.domain.config")
        domain = Domain(name="Test", root_path=str(tmp_path))

        domain.init(traverse=False)

        records = _no_config_records(caplog)
        assert len(records) == 1
        assert records[0].levelno == logging.DEBUG
        assert records[0].getMessage() == (
            f"No configuration file found in {domain.root_path} or its "
            "immediate 2 parent directories. Using default configuration."
        )

    def test_second_init_does_not_log_again(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG, logger="protean.domain.config")
        domain = Domain(name="Test", root_path=str(tmp_path))
        domain.init(traverse=False)
        assert len(_no_config_records(caplog)) == 1

        domain.init(traverse=False)

        assert len(_no_config_records(caplog)) == 1

    def test_explicit_config_logs_nothing(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG, logger="protean.domain.config")
        domain = Domain(
            name="Test",
            root_path=str(tmp_path),
            config={"databases": {"default": {"provider": "memory"}}},
        )

        domain.init(traverse=False)

        assert _no_config_records(caplog) == []

    def test_config_file_present_logs_nothing(self, tmp_path, caplog):
        (tmp_path / "domain.toml").write_text('[custom]\nFOO = "bar"\n')
        caplog.set_level(logging.DEBUG, logger="protean.domain.config")
        domain = Domain(name="Test", root_path=str(tmp_path))
        assert domain.config["custom"]["FOO"] == "bar"

        domain.init(traverse=False)

        assert _no_config_records(caplog) == []


class TestLoadingDefaults:
    def test_that_config_is_loaded_from_dict(self):
        from protean.domain.config import _default_config

        config_dict = _default_config()
        config_dict["custom"] = {"FOO": "bar", "qux": "quux"}
        config = Config2.load_from_dict(config_dict)
        assert config["databases"]["default"]["provider"] == "memory"
        assert config["custom"]["FOO"] == "bar"
        assert config["custom"]["qux"] == "quux"

    def test_that_config_defaults_when_none_passed(self):
        # Omitting the argument (or passing ``None``) falls back to the
        # default config rather than a mutable import-time default.
        config = Config2.load_from_dict()
        assert config["databases"]["default"]["provider"] == "memory"


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
