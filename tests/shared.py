"""Shared utilities for tests"""

import os
import sys

from pathlib import Path
from uuid import UUID

import pytest

from protean.domain import Domain


def initialize_domain(file_path):
    """Initialize a Protean Domain with configuration from a file"""
    domain = Domain(__file__, "Tests")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(file_path))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    # Reinitialize the domain after config changes
    domain._initialize()

    return domain


def assert_str_is_uuid(value: str) -> None:
    """Assert that a string is a valid UUID"""
    try:
        UUID(value)
    except ValueError:
        pytest.fail("Invalid UUID")


def change_working_directory_to(path):
    """Change working directory to a specific test directory
    and add it to the Python path so that the test can import.

    The test directory is expected to be in `support/test_domains`.
    """
    test_path = (Path(__file__) / ".." / "support" / "test_domains" / path).resolve()

    os.chdir(test_path)
    sys.path.insert(0, test_path)
