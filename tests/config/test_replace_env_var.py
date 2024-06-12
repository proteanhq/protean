import os

import pytest
from mock import patch

from protean.domain.config import Config2
from protean.exceptions import ConfigurationError


@pytest.fixture
def env_vars():
    with patch.dict(os.environ, {"ENV_VAR1": "value1", "ENV_VAR2": "value2"}):
        yield


def test_replace_env_var_single(env_vars):
    input_string = "${ENV_VAR1}"
    result = Config2._replace_env_var(input_string)
    assert result == "value1"


def test_replace_env_var_multiple(env_vars):
    input_string = "${ENV_VAR1} and ${ENV_VAR2}"
    result = Config2._replace_env_var(input_string)
    assert result == "value1 and value2"


def test_replace_env_var_mixed(env_vars):
    input_string = "prefix_${ENV_VAR1}_suffix and ${ENV_VAR2}_end"
    result = Config2._replace_env_var(input_string)
    assert result == "prefix_value1_suffix and value2_end"


def test_replace_env_var_no_env_var():
    input_string = "${UNDEFINED_ENV_VAR}"

    with pytest.raises(ConfigurationError) as exc:
        Config2._replace_env_var(input_string)
    assert exc.value.args[0] == "Environment variable UNDEFINED_ENV_VAR is not set"


def test_replace_env_var_partial(env_vars):
    input_string = (
        "This is a test with ${ENV_VAR1} and an undefined ${UNDEFINED_ENV_VAR}"
    )

    with pytest.raises(ConfigurationError) as exc:
        Config2._replace_env_var(input_string)
    assert exc.value.args[0] == "Environment variable UNDEFINED_ENV_VAR is not set"


def test_replace_env_var_no_placeholders():
    input_string = "This is a static value"
    result = Config2._replace_env_var(input_string)
    assert result == "This is a static value"
