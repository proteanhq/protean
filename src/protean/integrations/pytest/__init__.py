"""Pytest integration for Protean.

Provides `DomainFixture` for managing the domain lifecycle in tests,
and an auto-registered pytest plugin that sets ``PROTEAN_ENV`` before
test collection.

The adapter conformance suites of every port run from a source checkout under
``tests/conformance/``, whose ``conftest.py`` is their plugin. The older
database-only plugin, ``protean.integrations.pytest.adapter_conformance``, is
deprecated: importing it raises ``RemovedInProtean020Warning``, and it is
removed in 0.20.0.

For event-sourcing test DSL, use [`protean.testing`][protean.testing]::

    from protean.testing import given

For asserting query shape and round-trip count, use the query assertions::

    from protean.integrations.pytest import assert_query_count
"""

from .query_assertions import (
    assert_no_overfetch,
    assert_no_subquery_wrap,
    assert_query_count,
    capture_queries,
)
from .testbed import DomainFixture

__all__ = [
    "DomainFixture",
    "assert_no_overfetch",
    "assert_no_subquery_wrap",
    "assert_query_count",
    "capture_queries",
]
