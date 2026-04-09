"""Tests for shared health check utilities."""

from unittest.mock import MagicMock, patch

import pytest

from protean.domain import Domain
from protean.utils.health import (
    STATUS_OK,
    STATUS_UNAVAILABLE,
    check_brokers,
    check_caches,
    check_event_store,
    check_providers,
)


@pytest.fixture
def domain():
    d = Domain(name="HealthUtilTest")
    d.init(traverse=False)
    return d


# ---------------------------------------------------------------------------
# check_providers
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckProviders:
    def test_ok_with_memory_provider(self, domain):
        with domain.domain_context():
            statuses, all_ok = check_providers(domain)
            assert all_ok is True
            for v in statuses.values():
                assert v == STATUS_OK

    def test_returns_unavailable_when_provider_returns_false(self, domain):
        with domain.domain_context():
            for p in domain.providers.values():
                p.is_alive = lambda: False
            statuses, all_ok = check_providers(domain)
            assert all_ok is False
            for v in statuses.values():
                assert v == STATUS_UNAVAILABLE

    def test_returns_unavailable_when_provider_raises(self, domain):
        with domain.domain_context():
            for p in domain.providers.values():
                p.is_alive = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            statuses, all_ok = check_providers(domain)
            assert all_ok is False

    def test_handles_broken_providers_iterator(self, domain):
        """Outer except catches errors from iterating providers."""
        with domain.domain_context():
            with patch.object(
                type(domain.providers), "items", side_effect=RuntimeError("broken")
            ):
                statuses, all_ok = check_providers(domain)
                assert all_ok is False
                assert "_error" in statuses


# ---------------------------------------------------------------------------
# check_brokers
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckBrokers:
    def test_ok_with_inline_broker(self, domain):
        with domain.domain_context():
            statuses, all_ok = check_brokers(domain)
            assert all_ok is True

    def test_returns_unavailable_when_broker_returns_false(self, domain):
        with domain.domain_context():
            for b in domain.brokers.values():
                b.ping = lambda: False
            statuses, all_ok = check_brokers(domain)
            assert all_ok is False

    def test_returns_unavailable_when_broker_raises(self, domain):
        with domain.domain_context():
            for b in domain.brokers.values():
                b.ping = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            statuses, all_ok = check_brokers(domain)
            assert all_ok is False

    def test_handles_broken_brokers_iterator(self, domain):
        with domain.domain_context():
            with patch.object(
                type(domain.brokers), "items", side_effect=RuntimeError("broken")
            ):
                statuses, all_ok = check_brokers(domain)
                assert all_ok is False
                assert "_error" in statuses


# ---------------------------------------------------------------------------
# check_event_store
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckEventStore:
    def test_ok_with_memory_event_store(self, domain):
        with domain.domain_context():
            status, ok = check_event_store(domain)
            assert ok is True
            assert status == STATUS_OK

    def test_unavailable_when_event_store_raises(self, domain):
        with domain.domain_context():
            domain.event_store.store._read_last_message = lambda _: (
                _ for _ in ()
            ).throw(RuntimeError("down"))
            status, ok = check_event_store(domain)
            assert ok is False
            assert status == STATUS_UNAVAILABLE


# ---------------------------------------------------------------------------
# check_caches
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckCaches:
    def test_ok_with_memory_cache(self, domain):
        with domain.domain_context():
            statuses, all_ok = check_caches(domain)
            assert all_ok is True

    def test_ok_when_cache_has_no_ping(self, domain):
        """Caches without a ping() method are treated as available."""
        with domain.domain_context():
            mock_cache = MagicMock(spec=[])  # No ping attribute
            with patch.object(
                type(domain.caches), "items", return_value=[("no-ping", mock_cache)]
            ):
                statuses, all_ok = check_caches(domain)
                assert all_ok is True
                assert statuses["no-ping"] == STATUS_OK

    def test_returns_unavailable_when_cache_ping_returns_false(self, domain):
        with domain.domain_context():
            for c in domain.caches.values():
                c.ping = lambda: False
            statuses, all_ok = check_caches(domain)
            assert all_ok is False
            for v in statuses.values():
                assert v == STATUS_UNAVAILABLE

    def test_returns_unavailable_when_cache_ping_raises(self, domain):
        with domain.domain_context():
            for c in domain.caches.values():
                c.ping = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            statuses, all_ok = check_caches(domain)
            assert all_ok is False

    def test_handles_broken_caches_iterator(self, domain):
        with domain.domain_context():
            with patch.object(
                type(domain.caches), "items", side_effect=RuntimeError("broken")
            ):
                statuses, all_ok = check_caches(domain)
                assert all_ok is False
                assert "_error" in statuses
