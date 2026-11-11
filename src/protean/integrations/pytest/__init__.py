"""Pytest integration for Protean.

Provides `DomainFixture` for managing the domain lifecycle in tests,
and an auto-registered pytest plugin that sets ``PROTEAN_ENV`` before
test collection.

The adapter conformance plugin for every port is ``tests/conformance/conftest.py``
in a source checkout, with one folder per port under ``tests/conformance/``. The
older database-only plugin, ``protean.integrations.pytest.adapter_conformance``,
is deprecated: importing it raises ``RemovedInProtean020Warning``, and it is
removed in 0.20.0. Run ``protean test test-adapter --provider <name>`` from a
source checkout instead.

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
