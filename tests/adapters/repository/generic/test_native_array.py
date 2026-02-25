"""Generic native array storage tests for providers with NATIVE_ARRAY capability.

Covers native array persistence, order preservation, empty lists, and
multiple element types. These tests only run against providers that declare
NATIVE_ARRAY in their capabilities (e.g., PostgreSQL).
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import List, String


class ArrayHolder(BaseAggregate):
    name: String(max_length=100, required=True)
    items: List(content_type=String)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(ArrayHolder)
    test_domain.init(traverse=False)


@pytest.mark.native_array
class TestNativeArrayStorage:
    """Persist aggregates with list data and verify values and order."""

    def test_persist_string_list(self, test_domain):
        holder = ArrayHolder(
            name="strings",
            items=["alpha", "beta", "gamma"],
        )
        test_domain.repository_for(ArrayHolder).add(holder)

        retrieved = test_domain.repository_for(ArrayHolder).get(holder.id)
        assert retrieved.items == ["alpha", "beta", "gamma"]

    def test_order_is_preserved(self, test_domain):
        holder = ArrayHolder(
            name="ordered",
            items=["z", "a", "m", "b"],
        )
        test_domain.repository_for(ArrayHolder).add(holder)

        retrieved = test_domain.repository_for(ArrayHolder).get(holder.id)
        assert retrieved.items == ["z", "a", "m", "b"]

    def test_persist_empty_list(self, test_domain):
        holder = ArrayHolder(name="empty", items=[])
        test_domain.repository_for(ArrayHolder).add(holder)

        retrieved = test_domain.repository_for(ArrayHolder).get(holder.id)
        assert retrieved.items == []

    def test_persist_default_list(self, test_domain):
        holder = ArrayHolder(name="default-list")
        test_domain.repository_for(ArrayHolder).add(holder)

        retrieved = test_domain.repository_for(ArrayHolder).get(holder.id)
        # List fields default to empty list when not provided
        assert retrieved.items == []


@pytest.mark.native_array
class TestNativeArrayTypes:
    """Test lists of various element types stored as native arrays."""

    def test_list_of_strings(self, test_domain):
        holder = ArrayHolder(
            name="string-list",
            items=["hello", "world"],
        )
        test_domain.repository_for(ArrayHolder).add(holder)

        retrieved = test_domain.repository_for(ArrayHolder).get(holder.id)
        assert retrieved.items == ["hello", "world"]
        assert all(isinstance(item, str) for item in retrieved.items)

    def test_single_element_list(self, test_domain):
        holder = ArrayHolder(name="single", items=["only"])
        test_domain.repository_for(ArrayHolder).add(holder)

        retrieved = test_domain.repository_for(ArrayHolder).get(holder.id)
        assert retrieved.items == ["only"]
        assert len(retrieved.items) == 1

    def test_list_with_duplicate_values(self, test_domain):
        holder = ArrayHolder(
            name="duplicates",
            items=["repeat", "repeat", "unique"],
        )
        test_domain.repository_for(ArrayHolder).add(holder)

        retrieved = test_domain.repository_for(ArrayHolder).get(holder.id)
        assert retrieved.items == ["repeat", "repeat", "unique"]
