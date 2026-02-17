"""Tests for DomainFixture."""

from unittest import mock

import pytest

from protean.domain import Domain
from protean.integrations.pytest import DomainFixture


@pytest.fixture
def domain():
    """Create a minimal test domain."""
    return Domain(name="testbed_domain")


class TestSetup:
    """Tests for DomainFixture.setup()."""

    def test_calls_domain_init(self, domain):
        """setup() calls domain.init()."""
        bed = DomainFixture(domain)

        with mock.patch.object(domain, "init") as mock_init:
            # Mock providers to avoid real DB calls
            domain.providers = {}
            bed.setup()
            mock_init.assert_called_once()

    def test_creates_database_artifacts(self, domain):
        """setup() calls _create_database_artifacts on each provider."""
        bed = DomainFixture(domain)
        mock_provider = mock.MagicMock()

        with mock.patch.object(domain, "init"):
            domain.providers = {"default": mock_provider}
            bed.setup()
            mock_provider._create_database_artifacts.assert_called_once()


class TestTeardown:
    """Tests for DomainFixture.teardown()."""

    def test_drops_database_artifacts(self, domain):
        """teardown() calls _drop_database_artifacts on each provider."""
        bed = DomainFixture(domain)
        mock_provider = mock.MagicMock()
        domain.providers = {"default": mock_provider}

        bed.teardown()
        mock_provider._drop_database_artifacts.assert_called_once()


class TestDomainContext:
    """Tests for DomainFixture.domain_context()."""

    def test_yields_domain(self, domain):
        """Context manager yields the domain instance."""
        bed = DomainFixture(domain)

        # Mock the stores to avoid real infrastructure
        mock_provider = mock.MagicMock()
        mock_broker = mock.MagicMock()
        mock_event_store = mock.MagicMock()
        domain.providers = {"default": mock_provider}
        domain.brokers = {"default": mock_broker}
        domain.event_store = mock_event_store

        with bed.domain_context() as ctx_domain:
            assert ctx_domain is domain

    def test_resets_providers(self, domain):
        """Context manager resets all providers on exit."""
        bed = DomainFixture(domain)

        mock_provider = mock.MagicMock()
        mock_broker = mock.MagicMock()
        mock_event_store = mock.MagicMock()
        domain.providers = {"default": mock_provider}
        domain.brokers = {"default": mock_broker}
        domain.event_store = mock_event_store

        with bed.domain_context():
            pass

        mock_provider._data_reset.assert_called_once()

    def test_resets_brokers(self, domain):
        """Context manager resets all brokers on exit."""
        bed = DomainFixture(domain)

        mock_provider = mock.MagicMock()
        mock_broker = mock.MagicMock()
        mock_event_store = mock.MagicMock()
        domain.providers = {"default": mock_provider}
        domain.brokers = {"default": mock_broker}
        domain.event_store = mock_event_store

        with bed.domain_context():
            pass

        mock_broker._data_reset.assert_called_once()

    def test_resets_event_store(self, domain):
        """Context manager resets event store on exit."""
        bed = DomainFixture(domain)

        mock_provider = mock.MagicMock()
        mock_broker = mock.MagicMock()
        mock_event_store = mock.MagicMock()
        domain.providers = {"default": mock_provider}
        domain.brokers = {"default": mock_broker}
        domain.event_store = mock_event_store

        with bed.domain_context():
            pass

        mock_event_store.store._data_reset.assert_called_once()

    def test_cleanup_on_exception(self, domain):
        """Data stores are reset even when the test raises an exception."""
        bed = DomainFixture(domain)

        mock_provider = mock.MagicMock()
        mock_broker = mock.MagicMock()
        mock_event_store = mock.MagicMock()
        domain.providers = {"default": mock_provider}
        domain.brokers = {"default": mock_broker}
        domain.event_store = mock_event_store

        with pytest.raises(RuntimeError):
            with bed.domain_context():
                raise RuntimeError("test failure")

        # Cleanup still happens
        mock_provider._data_reset.assert_called_once()
        mock_broker._data_reset.assert_called_once()
        mock_event_store.store._data_reset.assert_called_once()

    def test_activates_domain_context(self, domain):
        """current_domain resolves to the correct domain inside the context."""
        bed = DomainFixture(domain)

        mock_provider = mock.MagicMock()
        mock_broker = mock.MagicMock()
        mock_event_store = mock.MagicMock()
        domain.providers = {"default": mock_provider}
        domain.brokers = {"default": mock_broker}
        domain.event_store = mock_event_store

        from protean.utils.globals import current_domain

        with bed.domain_context():
            assert current_domain.name == "testbed_domain"
