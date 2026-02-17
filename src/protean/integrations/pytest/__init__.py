"""Pytest integration for Protean.

Provides :class:`DomainFixture` for managing the domain lifecycle in tests
and an auto-registered pytest plugin that sets ``PROTEAN_ENV`` before
test collection.
"""

from .testbed import DomainFixture

__all__ = [
    "DomainFixture",
]
