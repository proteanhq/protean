import logging
import os
import tomllib


from protean.utils import deep_merge

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
                    print("No config file found, using defaults")
                    config_file_name = None

        config = {}
        if config_file_name:
            with open(config_file_name, "rb") as f:
                config = tomllib.load(f)

        config = deep_merge(defaults, config)

        return cls(**config)
