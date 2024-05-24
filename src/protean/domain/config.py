import logging
import os
import re
import tomllib

from protean.exceptions import ConfigurationError


logger = logging.getLogger(__name__)


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
    def load(cls, path: str, defaults: dict = None):
        # Derive the path of parent directory
        dir_path = os.path.abspath(os.path.dirname(path))

        # Find config files in the directory in the following order:
        # 1. .domain.toml
        # 2. domain.toml
        # 3. pyproject.toml
        config_file_name = os.path.join(dir_path, ".domain.toml")
        if not os.path.exists(config_file_name):
            config_file_name = os.path.join(dir_path, "domain.toml")
            if not os.path.exists(config_file_name):
                config_file_name = os.path.join(dir_path, "pyproject.toml")
                if not os.path.exists(config_file_name):
                    raise ConfigurationError(
                        f"No configuration file found in {dir_path}"
                    )

        config = {}
        if config_file_name:
            with open(config_file_name, "rb") as f:
                config = tomllib.load(f)

        # Merge with defaults
        config = cls._deep_merge(defaults, config)

        # Load environment variables
        config = cls._load_env_vars(config)

        return cls(**config)

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
        match = cls.ENV_VAR_PATTERN.search(value)
        while match:
            env_var = match.group(1)
            env_value = os.getenv(env_var)

            if env_value is None:
                raise ConfigurationError(f"Environment variable {env_var} is not set")

            value = value.replace(f"${{{env_var}}}", env_value)
            match = cls.ENV_VAR_PATTERN.search(value)

        return value
