"""The helpers ``BaseRepository`` calls to save an aggregate and its child
entities are module-level functions and never methods, because a user
repository that defines a method of the same name would replace the helper
with no error."""

import inspect

import pytest

from protean.core import repository
from protean.core.repository import BaseRepository

HELPERS = [
    "_save_root",
    "_raise_fact_event",
    "_direct_children",
    "_sync_has_many",
    "_sync_has_one",
    "_sync_has_one_change",
    "_sync_grandchildren",
    "_clear_caches",
]


@pytest.mark.parametrize("name", HELPERS)
def test_helper_is_a_module_level_function(name):
    helper = getattr(repository, name)

    assert inspect.isfunction(helper)
    assert helper.__qualname__ == name
    assert helper.__module__ == repository.__name__


@pytest.mark.parametrize("name", HELPERS)
def test_helper_is_not_an_attribute_of_base_repository(name):
    assert not hasattr(BaseRepository, name)
