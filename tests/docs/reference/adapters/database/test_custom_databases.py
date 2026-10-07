"""Run the example on ``docs/reference/adapters/database/custom-databases.md``.

The example is the ``delegating_provider`` package. The provider registry
stores a provider by its dotted import path, so the package's folder goes on
``sys.path`` and the test imports it by name.
"""

import re
import sys

import pytest

from tests.docs.support import DOCS, DOCS_SRC

_PACKAGE_PARENT = str(DOCS_SRC / "adapters" / "database" / "custom-databases")
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

import delegating_provider

from protean.adapters.repository.memory import MemoryProvider
from protean.exceptions import ObjectNotFoundError
from protean.port.provider import BaseProvider

pytestmark = pytest.mark.no_test_domain


def test_page_lists_every_abstract_method():
    page = (DOCS / "reference/adapters/database/custom-databases.md").read_text()
    section = page.split("### 1. Provider")[1].split("### 2.")[0]
    listed = set(re.findall(r"^\| `(\w+)", section, flags=re.MULTILINE))

    assert listed == BaseProvider.__abstractmethods__


def test_provider_registers_every_required_lookup():
    assert delegating_provider.DelegatingProvider.validate_lookups() == []


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

    assert (delegating_provider.customer.id, delegating_provider.customer.name) == (
        "c-1",
        "Ada",
    )
    assert (customer.id, customer.name) == ("c-1", "Ada")


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
