"""The helpers ``UnitOfWork`` calls during a commit are module-level functions
and never methods, because a subclass that defines a method of the same name
would replace the helper with no error."""

import inspect

import pytest

from protean.core import unit_of_work
from protean.core.unit_of_work import UnitOfWork

HELPERS = [
    "_record_events_raised",
    "_warn_multiple_aggregate_types",
    "_build_outbox_rows",
    "_provider_outbox_rows",
    "_outbox_rows_for_event",
    "_flush_sessions",
    "_append_events",
    "_save_outbox_rows",
    "_commit_sessions",
    "_record_commit_success",
]


@pytest.mark.parametrize("name", HELPERS)
def test_helper_is_a_module_level_function(name):
    helper = getattr(unit_of_work, name)

    assert inspect.isfunction(helper)
    assert helper.__qualname__ == name
    assert helper.__module__ == unit_of_work.__name__


@pytest.mark.parametrize("name", HELPERS)
def test_helper_is_not_an_attribute_of_unit_of_work(name):
    assert not hasattr(UnitOfWork, name)
