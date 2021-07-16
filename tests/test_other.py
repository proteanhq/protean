"""Module to test other Protean Functions and Utilities"""

import pytest

from protean.core import entity
from protean.utils.importlib import perform_import


def test_perform_import():
    """ Test the perform import function """

    # Test importing of None
    mod = perform_import(None)
    assert mod is None

    # Test import of string
    mod = perform_import("protean.core.entity")
    assert mod == entity

    # Test import list
    mod = perform_import(
        ["protean.core.entity.BaseEntity", "protean.core.entity._EntityMetaclass"]
    )
    assert mod == [entity.BaseEntity, entity._EntityMetaclass]

    # Test Failed import
    with pytest.raises(ImportError):
        perform_import("protean.core.entity.xxxx")

    # Test Direct import
    mod = perform_import(entity)
    assert mod == entity
