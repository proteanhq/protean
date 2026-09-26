"""Tests for DomainFixture."""

from unittest import mock

import pytest

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.domain.context import _domain_ctx_stack
from protean.fields import String
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

        with pytest.raises(RuntimeError), bed.domain_context():
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


def _mock_stores(domain):
    """Replace the domain's stores with mocks and return them."""
    domain.providers = {"default": mock.MagicMock()}
    domain.brokers = {"default": mock.MagicMock()}
    domain.event_store = mock.MagicMock()
    return (
        domain.providers["default"],
        domain.brokers["default"],
        domain.event_store.store,
    )


def _restore_ctx_stack(top):
    """Pop contexts off the global stack until ``top`` is on top again."""
    while _domain_ctx_stack.top is not None and _domain_ctx_stack.top is not top:
        _domain_ctx_stack.pop()
    assert _domain_ctx_stack.top is top


class _ItemA(BaseAggregate):
    name = String(max_length=50)


class _ItemB(BaseAggregate):
    name = String(max_length=50)


def _memory_domain(name, aggregate_cls):
    domain = Domain(name=name)
    domain.config["databases"]["default"] = {"provider": "memory"}
    domain.register(aggregate_cls)
    domain.init(traverse=False)
    return domain


def _count(domain, aggregate_cls):
    with domain.domain_context():
        return domain.repository_for(aggregate_cls)._dao.query.all().total


class TestDomainContextIsolation:
    """domain_context() resets its own domain's data, whatever else is pushed."""

    def test_leaked_context_resets_only_the_fixture_domain(self):
        domain_a = Domain(name="domain_a")
        domain_b = Domain(name="domain_b")
        provider_a, broker_a, store_a = _mock_stores(domain_a)
        provider_b, broker_b, store_b = _mock_stores(domain_b)
        bed_a = DomainFixture(domain_a)

        top_before = _domain_ctx_stack.top
        try:
            with (
                pytest.raises(AssertionError, match="Popped wrong domain context"),
                bed_a.domain_context(),
            ):
                # Leave domain B's context pushed when the test body ends
                domain_b.domain_context().push()

            # The leaked context and the fixture's own context are both gone
            assert _domain_ctx_stack.top is top_before
        finally:
            _restore_ctx_stack(top_before)

        provider_a._data_reset.assert_called_once()
        broker_a._data_reset.assert_called_once()
        store_a._data_reset.assert_called_once()
        provider_b._data_reset.assert_not_called()
        broker_b._data_reset.assert_not_called()
        store_b._data_reset.assert_not_called()

    @pytest.mark.no_test_domain
    def test_leaked_context_keeps_the_other_domain_data(self):
        domain_a = _memory_domain("domain_a", _ItemA)
        domain_b = _memory_domain("domain_b", _ItemB)
        bed_a = DomainFixture(domain_a)

        with domain_b.domain_context():
            domain_b.repository_for(_ItemB).add(_ItemB(name="b"))

        top_before = _domain_ctx_stack.top
        try:
            with (
                pytest.raises(AssertionError, match="Popped wrong domain context"),
                bed_a.domain_context(),
            ):
                domain_a.repository_for(_ItemA).add(_ItemA(name="a"))
                assert _count(domain_a, _ItemA) == 1

                domain_b.domain_context().push()
        finally:
            _restore_ctx_stack(top_before)

        assert _count(domain_a, _ItemA) == 0
        assert _count(domain_b, _ItemB) == 1

    def test_leaked_context_leaves_stack_below_untouched(self, domain):
        _mock_stores(domain)
        bed = DomainFixture(domain)
        outer = Domain(name="outer").domain_context()
        outer.push()

        try:
            with pytest.raises(AssertionError, match="Popped wrong domain context"):
                with bed.domain_context():
                    Domain(name="leaked").domain_context().push()
                    Domain(name="leaked_too").domain_context().push()

            assert _domain_ctx_stack.top is outer
        finally:
            outer.pop()

    def test_stack_is_unchanged_when_the_fixture_context_is_already_gone(self, domain):
        _mock_stores(domain)
        bed = DomainFixture(domain)
        top_before = _domain_ctx_stack.top

        try:
            with pytest.raises(AssertionError, match="Popped wrong domain context"):
                with bed.domain_context():
                    # Pop the fixture's own context, then push two others
                    _domain_ctx_stack.pop()
                    first = Domain(name="first").domain_context()
                    first.push()
                    Domain(name="second").domain_context().push()

            # Only the top context was popped; ``first`` is still there
            assert _domain_ctx_stack.top is first
        finally:
            _restore_ctx_stack(top_before)

    def test_context_is_popped_when_a_reset_raises(self, domain):
        provider, _broker, _store = _mock_stores(domain)
        provider._data_reset.side_effect = RuntimeError("reset failed")
        bed = DomainFixture(domain)
        teardown = mock.Mock()
        domain.teardown_domain_context(teardown)

        top_before = _domain_ctx_stack.top
        try:
            with pytest.raises(RuntimeError, match="reset failed"):
                with bed.domain_context():
                    pass

            assert _domain_ctx_stack.top is top_before
            teardown.assert_called_once()
        finally:
            _restore_ctx_stack(top_before)


class TestSetupDelegatesToPublicAPI:
    """Verify DomainFixture delegates to Domain's public lifecycle methods."""

    def test_setup_calls_setup_database(self, domain):
        """setup() delegates to domain.setup_database()."""
        bed = DomainFixture(domain)

        with mock.patch.object(domain, "init"):
            with mock.patch.object(domain, "setup_database") as mock_setup:
                domain.domain_context = mock.MagicMock()
                domain.domain_context.return_value.__enter__ = mock.MagicMock()
                domain.domain_context.return_value.__exit__ = mock.MagicMock(
                    return_value=False
                )

                bed.setup()
                mock_setup.assert_called_once()

    def test_teardown_calls_drop_database(self, domain):
        """teardown() delegates to domain.drop_database()."""
        bed = DomainFixture(domain)

        with mock.patch.object(domain, "drop_database") as mock_drop:
            domain.domain_context = mock.MagicMock()
            domain.domain_context.return_value.__enter__ = mock.MagicMock()
            domain.domain_context.return_value.__exit__ = mock.MagicMock(
                return_value=False
            )

            bed.teardown()
            mock_drop.assert_called_once()
