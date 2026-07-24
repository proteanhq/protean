"""Shared fixtures for the correctness property suite (:issue:`#1251`).

These tests run against their own ``verification_domain`` (defined in
``strategies.py``) rather than the autouse ``test_domain`` fixture, so every
module here is marked ``no_test_domain``. A module-scoped fixture activates the
domain context once per module — module scope (not function) keeps Hypothesis'
``function_scoped_fixture`` health check happy.
"""

import pytest

from tests.verification.strategies import verification_domain


@pytest.fixture(autouse=True, scope="module")
def _verification_domain_context():
    with verification_domain.domain_context():
        yield
