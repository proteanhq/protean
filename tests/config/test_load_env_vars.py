import os

import pytest
from mock import patch

from protean.domain.config import Config2
from protean.exceptions import ConfigurationError
from protean.utils.domain_discovery import derive_domain
from tests.shared import change_working_directory_to


@pytest.fixture
def env_vars():
    with patch.dict(
        os.environ, {"ENV_VAR1": "value1", "ENV_VAR2": "value2", "ENV_VAR3": "value3"}
    ):
        yield


def test_load_env_vars_single_string(env_vars):
    config = {"key1": "${ENV_VAR1}", "key2": "static_value"}
    result = Config2._load_env_vars(config)
    assert result["key1"] == "value1"
    assert result["key2"] == "static_value"


def test_load_env_vars_nested_dict(env_vars):
    config = {
        "key1": "${ENV_VAR1}",
        "nested": {"key2": "${ENV_VAR2}", "key3": "static_value"},
    }
    result = Config2._load_env_vars(config)
    assert result["key1"] == "value1"
    assert result["nested"]["key2"] == "value2"
    assert result["nested"]["key3"] == "static_value"


def test_load_env_vars_list(env_vars):
    config = {"key1": ["${ENV_VAR1}", "${ENV_VAR2}", "static_value"]}
    result = Config2._load_env_vars(config)
    assert result["key1"] == ["value1", "value2", "static_value"]


def test_load_env_vars_mixed(env_vars):
    config = {
        "key1": "${ENV_VAR1}",
        "nested": {"key2": ["${ENV_VAR2}", "static_value"], "key3": "static_value"},
        "key4": ["${ENV_VAR3}", "${ENV_VAR1}"],
    }
    result = Config2._load_env_vars(config)
    assert result["key1"] == "value1"
    assert result["nested"]["key2"] == ["value2", "static_value"]
    assert result["nested"]["key3"] == "static_value"
    assert result["key4"] == ["value3", "value1"]


def test_load_env_vars_no_env_var():
    config = {"key1": "${UNDEFINED_ENV_VAR}", "key2": "static_value"}
    with pytest.raises(ConfigurationError) as exc:
        Config2._load_env_vars(config)

    assert exc.value.args[0] == "Environment variable UNDEFINED_ENV_VAR is not set"


@patch.dict(
    os.environ,
    {
        "DB_USER": "test_user",
        "DB_PASSWORD": "test_pass",
        "SQLITE_DB_LOCATION": "sqlite:///test.db",
    },
)
def test_load_env_vars():
    change_working_directory_to("test18")

    domain = derive_domain("domain18")
    assert domain.config["custom"]["FOO_USER"] == "test_user"
    assert domain.config["custom"]["FOO_PASSWORD"] == "test_pass"
    assert (
        domain.config["databases"]["secondary"]["database_uri"] == "sqlite:///test.db"
    )


def test_default_fallback():
    config = {"secret_key": "${SECRET_KEY|this-is-a-secret-key}"}
    result = Config2._load_env_vars(config)
    assert result["secret_key"] == "this-is-a-secret-key"
