"""Pytest integration for Protean.

Provides :class:`DomainFixture` for managing the domain lifecycle in tests,
and an auto-registered pytest plugin that sets ``PROTEAN_ENV`` before
test collection.

For running generic database adapter conformance tests from an external
adapter package, load the conformance plugin in your ``conftest.py``::

    pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]

For event-sourcing test DSL, use :mod:`protean.testing`::

    from protean.testing import given
"""

from .testbed import DomainFixture

__all__ = [
    "DomainFixture",
]
