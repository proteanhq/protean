"""Run the example on ``docs/reference/adapters/database/custom-databases.md``.

The example is the ``delegating_provider`` package. The provider registry
stores a provider by its dotted import path, so the package's folder goes on
``sys.path`` and the test imports it by name.
"""

import sys

import pytest

from tests.docs.support import DOCS_SRC

_PACKAGE_PARENT = str(DOCS_SRC / "adapters" / "database" / "custom-databases")
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

import delegating_provider

from protean.adapters.repository.memory import MemoryProvider
from protean.exceptions import ObjectNotFoundError

pytestmark = pytest.mark.no_test_domain


def test_provider_implements_every_abstract_method():
    assert delegating_provider.DelegatingProvider.__abstractmethods__ == frozenset()


def test_domain_uses_the_custom_provider():
    with delegating_provider.domain.domain_context():
        provider = delegating_provider.domain.providers["default"]

        assert isinstance(provider, delegating_provider.DelegatingProvider)
        assert isinstance(provider._delegate, MemoryProvider)
        assert provider.__database__ == "delegating_memory"


def test_saved_aggregate_is_read_back():
    domain = delegating_provider.domain
    with domain.domain_context():
        customer = domain.repository_for(delegating_provider.Customer).get("c-1")

        assert customer.name == "Ada"


def test_raw_query_goes_through_the_delegate():
    with delegating_provider.domain.domain_context():
        provider = delegating_provider.domain.providers["default"]
        results = provider.raw('{"name": "Ada"}')

    assert [row["name"] for row in results] == ["Ada"]


def test_missing_aggregate_raises():
    domain = delegating_provider.domain
    with domain.domain_context():
        repo = domain.repository_for(delegating_provider.Customer)

        with pytest.raises(ObjectNotFoundError):
            repo.get("c-404")
