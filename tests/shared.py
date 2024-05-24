"""Shared utilities for tests"""

import os
import sys

from pathlib import Path
from uuid import UUID

import pytest

from protean.domain import Domain


def initialize_domain(file_path, name="Tests"):
    """Initialize a Protean Domain with configuration from a file"""
    domain = Domain(file_path, name=name)

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
    sys.path.insert(0, str(test_path))
