"""Shared utilities for tests"""

import os
import sys
from pathlib import Path
from uuid import UUID

import pytest

from protean.domain import Domain


def initialize_domain(name="Tests", root_path=None):
    """Initialize a Protean Domain with configuration from a file"""
    domain = Domain(name=name, root_path=root_path)

    # We initialize and load default configuration into the domain here
    #   so that test cases that don't need explicit domain setup can
    #   still function.
    domain._initialize()

    return domain


def assert_str_is_uuid(value: str) -> None:
    """Assert that a string is a valid UUID"""
    try:
        UUID(value)
    except ValueError:
        pytest.fail("Invalid UUID")


def assert_int_is_uuid(value: int) -> None:
    """Assert that an integer is a valid UUID"""
    try:
        UUID(int=value)
    except ValueError:
        pytest.fail("Invalid UUID")


def change_working_directory_to(path):
    """Change working directory to a specific test directory
    and add it to the Python path so that the test can import.

    The test directory is expected to be in `support/domains`.
    """
    test_path = (Path(__file__) / ".." / "support" / "domains" / path).resolve()

    os.chdir(test_path)
    sys.path.insert(0, str(test_path))


def has_key_or_attr(obj, name):
    try:
        return name in obj  # Works if obj is dict-like
    except TypeError:
        return hasattr(obj, name)


def get_value_from_key_or_attr(obj, name, default=None):
    """
    Retrieve a value from a dict or object by name.
    Returns `default` if key/attribute is missing.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
