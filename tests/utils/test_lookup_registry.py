"""Tests for ``split_lookup_key`` and ``RegisterLookupMixin.get_lookup``."""

import pytest

from protean.adapters.database.memory import Exact, MemoryDatabase
from protean.utils.query import split_lookup_key


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("name", ("name", "exact")),
        ("name__icontains", ("name", "icontains")),
        ("name__in", ("name", "in")),
    ],
)
def test_split_lookup_key(key, expected):
    assert split_lookup_key(key) == expected


@pytest.mark.no_test_domain
class TestGetLookup:
    def test_returns_the_registered_lookup(self):
        provider = MemoryDatabase("default", None, {})

        assert provider.get_lookup("exact") is Exact

    def test_unregistered_lookup_names_the_lookup_and_the_provider(self):
        provider = MemoryDatabase("primary", None, {})

        with pytest.raises(NotImplementedError) as exc_info:
            provider.get_lookup("nosuch")

        assert str(exc_info.value) == (
            "Lookup 'nosuch' is not registered on provider 'primary' (MemoryDatabase)"
        )

    def test_provider_without_a_name_is_named_by_its_class(self):
        provider = MemoryDatabase("", None, {})

        with pytest.raises(NotImplementedError) as exc_info:
            provider.get_lookup("nosuch")

        assert str(exc_info.value) == (
            "Lookup 'nosuch' is not registered on provider MemoryDatabase"
        )

    def test_class_that_does_not_subclass_the_port_is_rejected(self):
        class PlainLookup:
            lookup_name = "plain"

        MemoryDatabase.register_lookup(PlainLookup)
        try:
            provider = MemoryDatabase("primary", None, {})

            with pytest.raises(NotImplementedError) as exc_info:
                provider.get_lookup("plain")
        finally:
            MemoryDatabase._delist_lookup(PlainLookup)
            MemoryDatabase._clear_cached_lookups()

        assert str(exc_info.value) == (
            "Lookup 'plain' on provider 'primary' (MemoryDatabase) is "
            "PlainLookup, which does not subclass LookupPort"
        )
        assert "plain" not in MemoryDatabase.get_lookups()

    def test_function_registered_as_a_lookup_is_rejected(self):
        def plain_lookup(source, target):
            return source == target

        MemoryDatabase.register_lookup(plain_lookup, "plain")  # type: ignore[type-var]
        try:
            provider = MemoryDatabase("primary", None, {})

            with pytest.raises(NotImplementedError) as exc_info:
                provider.get_lookup("plain")
        finally:
            MemoryDatabase._delist_lookup(plain_lookup, "plain")  # type: ignore[arg-type]
            MemoryDatabase._clear_cached_lookups()

        assert str(exc_info.value) == (
            "Lookup 'plain' on provider 'primary' (MemoryDatabase) is "
            "plain_lookup, which does not subclass LookupPort"
        )
