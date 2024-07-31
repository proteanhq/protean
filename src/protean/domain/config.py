import logging
import os
import re

import tomllib

from protean.exceptions import ConfigurationError
from protean.utils import Processing

logger = logging.getLogger(__name__)


def _default_config():
    """Return the default configuration for a Protean application.

    This is placed in a separate function because we want to be absolutely
    sure that we are using a copy of the defaults when we manipulate config
    directly in tests. Housing it within the main `Domain` class can
    potentially lead to issues because the config can be overwritten by accident.
    """
    from protean.utils import IdentityStrategy, IdentityType

    return {
        "env": None,
        "testing": None,
        "debug": None,
        "secret_key": None,
        "identity_strategy": IdentityStrategy.UUID.value,
        "identity_type": IdentityType.STRING.value,
        "databases": {
            "default": {"provider": "memory"},
            "memory": {"provider": "memory"},
        },
        "event_processing": Processing.ASYNC.value,
        "command_processing": Processing.ASYNC.value,
        "message_processing": Processing.ASYNC.value,
        "event_store": {
            "provider": "memory",
        },
        "caches": {
            "default": {
                "provider": "memory",
                "TTL": 300,
            }
        },
        "brokers": {"default": {"provider": "inline"}},
        "email_providers": {
            "default": {
                "provider": "protean.adapters.DummyEmailProvider",
                "DEFAULT_FROM_EMAIL": "admin@team8solutions.com",
            },
        },
        "snapshot_threshold": 10,
        "custom": {},
    }


class ConfigAttribute:
    """Makes an attribute forward to the config"""

    def __init__(self, name):
        self.__name__ = name

    def __get__(self, obj, type=None):
        return obj.config[self.__name__]

    def __set__(self, obj, value):
        obj.config[self.__name__] = value


class Config2(dict):
    ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

    @classmethod
    def load_from_dict(cls, config: dict = _default_config()):
        """Load configuration from a dictionary."""
        return cls(**cls._normalize_config(config))

    @classmethod
    def load_from_path(cls, path: str):
        def find_config_file(directory: str):
            config_files = [".domain.toml", "domain.toml", "pyproject.toml"]
            for config_file in config_files:
                config_file_path = os.path.join(directory, config_file)
                if os.path.exists(config_file_path):
                    return config_file_path
            return None

        # Start checking from the provided path up to 2 parent directories
        current_dir = os.path.abspath(os.path.dirname(path))
        config_file_name = None

        for _ in range(3):  # Check the current directory and up to 2 parent directories
            config_file_name = find_config_file(current_dir)
            if config_file_name:
                break

            current_dir = os.path.dirname(current_dir)  # Move to the parent directory

        if not config_file_name:
            raise ConfigurationError(
                f"No configuration file found in {os.path.dirname(path)}"
            )

        config = {}
        if config_file_name:
            with open(config_file_name, "rb") as f:
                config = tomllib.load(f)

                # If pyproject.toml, extract protean configuration
                #   from the 'tool.protean' section
                if config_file_name.endswith("pyproject.toml"):
                    config = config.get("tool", {}).get("protean", {})

                config = cls._normalize_config(config)

        # Load environment variables
        config = cls._load_env_vars(config)

        return cls(**config)

    @classmethod
    def _normalize_config(cls, config):
        """Normalize configuration values.

        This method accepts a dictionary and combines the values from the
        configured environment to create a finalized configuration dictionary.
        """
        # Extract the value of PROTEAN_ENV environment variable
        environment = os.environ.get("PROTEAN_ENV") or None

        # Gather values of known variables
        keys = _default_config().keys()
        finalized_config = {key: value for key, value in config.items() if key in keys}

        # Merge with defaults
        finalized_config = cls._deep_merge(_default_config(), finalized_config)

        # Look for section linked to the specified environment
        if environment and environment in config:
            environment_config = config[environment]
            # Merge the environment section with the base configuration
            finalized_config = cls._deep_merge(finalized_config, environment_config)

        return finalized_config

    @classmethod
    def _deep_merge(cls, dict1: dict, dict2: dict):
        result = dict1.copy()
        for key, value in dict2.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @classmethod
    def _load_env_vars(cls, config):
        if isinstance(config, dict):
            for key, value in config.items():
                if isinstance(value, str):
                    config[key] = cls._replace_env_var(value)
                elif isinstance(value, dict):
                    config[key] = cls._load_env_vars(value)
                elif isinstance(value, list):
                    config[key] = [
                        cls._replace_env_var(item) if isinstance(item, str) else item
                        for item in value
                    ]
        return config

    @classmethod
    def _replace_env_var(cls, value):
        """Replace environment variables in a string.

        Cases:
        1. String does not have an environment variable. E.g. "attr-value" - Use as is
        2. String has an environment variable. E.g. "${ENV_VAR}" - Replace with value
        3. String has an environment variable with a default value. E.g. "${ENV_VAR|default-value}"
            - Replace with value or default value
        4. String has multiple environment variables. E.g. "${ENV_VAR1|default-value1} ${ENV_VAR2|default-value2}"
            - Replace all environment variables
        5. String has a mix of environment variables and static values. E.g. "attr-${ENV_VAR1|default-value1}"
            - Replace all environment variables
        """

        match = cls.ENV_VAR_PATTERN.search(value)
        while match:
            matched_string = match.group(1)

            if "|" in matched_string:
                # Default value provided
                env_var, default_value = matched_string.split("|", 1)
                env_value = os.getenv(env_var, default_value)
            else:
                # No default value provided
                env_value = os.getenv(matched_string)

            if env_value is None:
                raise ConfigurationError(
                    f"Environment variable {matched_string} is not set"
                )

            value = value.replace(f"${{{matched_string}}}", env_value)
            match = cls.ENV_VAR_PATTERN.search(value)

        return value
