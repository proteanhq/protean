import os

from uuid import UUID

import pytest


def initialize_domain(file_path):
    from protean.domain import Domain

    domain = Domain(__file__, "Tests")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(file_path))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    # Always reinitialize the domain after config changes
    domain.reinitialize()

    return domain


def assert_str_is_uuid(value: str) -> None:
    try:
        UUID(value)
    except ValueError:
        pytest.fail("Invalid UUID")
