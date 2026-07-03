"""Tests for ``BaseProvider.owns()`` — the single gate that decides whether a
provider materializes a table/index for a registered element.

Exercised here through the in-memory provider (a concrete ``BaseProvider``),
so these are core tests needing no external service. The gate replaces the
per-loop ``continue`` special-cases previously duplicated across the
SQLAlchemy and Elasticsearch providers.
"""

import pytest

from protean.domain import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.projection import BaseProjection
from protean.exceptions import ConfigurationError
from protean.fields import HasMany, Identifier, Integer, String


class Account(BaseAggregate):
    """A simple aggregate with no child associations."""

    balance: Integer()


class Order(BaseAggregate):
    name: String(required=True)
    items = HasMany("LineItem")


class LineItem(BaseEntity):
    sku: String(required=True)
    sub_items = HasMany("SubLineItem")


class SubLineItem(BaseEntity):
    """A 2nd-level entity — its immediate ``part_of`` is another entity."""

    detail: String()


class Leaderboard(BaseProjection):
    entry_id: Identifier(identifier=True)
    score: Integer()


def _register_order_cluster(domain, *, event_sourced: bool) -> None:
    """Register the Order → LineItem → SubLineItem cluster on ``domain``."""
    domain.register(Order, is_event_sourced=event_sourced)
    domain.register(LineItem, part_of=Order)
    domain.register(SubLineItem, part_of=LineItem)
    domain.init(traverse=False)


@pytest.mark.no_test_domain
class TestProviderOwns:
    """Positive and negative cases for the ownership gate."""

    def test_owns_regular_aggregate(self):
        """A regular aggregate is materialized by its (default) provider."""
        domain = Domain(name="Owns-Regular")
        domain.register(Account)
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            assert provider.owns(Account) is True

    def test_owns_entity_of_regular_aggregate(self):
        """A child entity of a regular (non-event-sourced) aggregate is still
        materialized — the event-sourced skip must only apply to event-sourced
        clusters."""
        domain = Domain(name="Owns-Regular-Entity")
        _register_order_cluster(domain, event_sourced=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            assert provider.owns(LineItem) is True

    def test_does_not_own_event_sourced_aggregate(self):
        """Event-sourced aggregates persist to the event store, not a table."""
        domain = Domain(name="Owns-ES-Aggregate")
        _register_order_cluster(domain, event_sourced=True)

        with domain.domain_context():
            provider = domain.providers["default"]
            assert provider.owns(Order) is False

    def test_does_not_own_entity_of_event_sourced_aggregate(self):
        """Direct entities of event-sourced aggregates follow the aggregate."""
        domain = Domain(name="Owns-ES-Entity")
        _register_order_cluster(domain, event_sourced=True)

        with domain.domain_context():
            provider = domain.providers["default"]
            assert provider.owns(LineItem) is False

    def test_does_not_own_nested_entity_of_event_sourced_aggregate(self):
        """A 2nd-level entity resolves its root aggregate via
        ``meta_.aggregate_cluster``. Its immediate ``part_of`` is a non-event-
        sourced entity, so a single-hop check would wrongly materialize it; the
        gate must follow the cluster to the event-sourced root and skip it."""
        domain = Domain(name="Owns-ES-Nested-Entity")
        _register_order_cluster(domain, event_sourced=True)

        with domain.domain_context():
            provider = domain.providers["default"]
            # Sanity: the nested entity's cluster is the event-sourced root.
            assert SubLineItem.meta_.aggregate_cluster is Order
            assert provider.owns(SubLineItem) is False

    def test_does_not_own_cache_backed_projection_without_raising(self):
        """A cache-backed projection carries ``meta_.provider is None``. The gate
        must return ``False`` without indexing ``providers[None]`` (which would
        raise, the latent Elasticsearch bug this consolidation fixes)."""
        domain = Domain(name="Owns-Cache-Projection")
        domain.register(Leaderboard, cache="default")
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            # meta_.provider is None for a cache-backed projection.
            assert Leaderboard.meta_.provider is None
            # Must not raise, and must report the provider does not own it.
            assert provider.owns(Leaderboard) is False

    def test_owns_database_backed_projection(self):
        """A projection persisted to a database provider (no ``cache``) defaults
        to ``provider='default'`` and is materialized by that provider."""
        domain = Domain(name="Owns-DB-Projection")
        domain.register(Leaderboard)  # database-backed (no cache)
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            assert Leaderboard.meta_.provider == "default"
            assert provider.owns(Leaderboard) is True

    def test_raises_for_unknown_provider_name(self):
        """An element referencing a provider name that is not configured is a
        misconfiguration — the gate must fail fast with ``ConfigurationError``
        instead of silently skipping the element during database setup."""
        domain = Domain(name="Owns-Unknown-Provider")
        domain.register(Account, provider="ghost")
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            with pytest.raises(ConfigurationError, match="ghost"):
                provider.owns(Account)

    def test_ownership_gate_is_provider_specific(self):
        """In a multi-provider domain, only the owning provider materializes an
        element; every other provider returns ``False``.

        The configured name and the element's ``provider`` are built as two
        distinct string objects with equal value (as they are in real usage:
        one parsed from ``domain.toml``, the other written in user code), so the
        gate's name *equality* is genuinely exercised — an object-identity
        (``is``) implementation would fail this test."""
        # ``"".join`` yields a fresh, non-interned object on each call.
        configured_name = "".join(["secondary", "-", "db"])
        element_name = "".join(["secondary", "-", "db"])
        assert configured_name == element_name and configured_name is not element_name

        domain = Domain(name="Owns-Multi-Provider")
        domain.config["databases"][configured_name] = {"provider": "memory"}
        domain.register(Account, provider=element_name)
        domain.init(traverse=False)

        with domain.domain_context():
            default_provider = domain.providers["default"]
            secondary_provider = domain.providers["secondary-db"]

            # Owned by the secondary provider only.
            assert Account.meta_.provider == "secondary-db"
            # The provider's own name is a different object than the element's.
            assert secondary_provider.name is not Account.meta_.provider
            assert secondary_provider.owns(Account) is True
            assert default_provider.owns(Account) is False
