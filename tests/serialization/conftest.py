"""Shared fixtures for the serialization round-trip suite.

These tests run against their own ``serialization_domain`` (defined in
``strategies.py``) rather than the autouse ``test_domain`` fixture, so every
module here is marked ``no_test_domain``. A module-scoped fixture activates the
domain context once per module — module scope (not function) keeps Hypothesis'
``function_scoped_fixture`` health check happy, and the context is read-only for
serialization so sharing it across a module's examples is safe.

Per-test Hypothesis settings live on the ``roundtrip_settings`` decorator in
``strategies.py`` rather than a loaded profile, to avoid mutating process-global
Hypothesis state from this sub-directory conftest.
"""

import pytest

from tests.serialization.strategies import serialization_domain


@pytest.fixture(autouse=True, scope="module")
def _serialization_domain_context():
    with serialization_domain.domain_context():
        yield
