import asyncio
from unittest.mock import MagicMock

import pytest

from protean import Engine
from protean.domain import Domain
from protean.exceptions import ConfigurationError


def test_that_engine_can_be_initialized_from_a_domain_object(test_domain):
    engine = Engine(test_domain)
    assert engine.domain == test_domain


def test_loop_initialization_within_engine(test_domain):
    engine = Engine(test_domain)
    assert engine.loop is not None
    assert isinstance(engine.loop, asyncio.SelectorEventLoop)
    assert engine.loop.is_running() is False
    assert engine.loop.is_closed() is False


# ---------------------------------------------------------------------------
# Observatory config fallback
# ---------------------------------------------------------------------------
class TestEngineObservatoryConfigFallback:
    """Test that Engine falls back to default trace_retention_days on bad config."""

    @pytest.mark.no_test_domain
    def test_fallback_when_observatory_config_missing(self):
        """Engine uses default retention when observatory config is absent."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        # Remove observatory key entirely
        domain.config.pop("observatory", None)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            assert engine.emitter._persist is True
            # Default is 7 days
            assert engine.emitter._retention_ms == 7 * 86_400_000

    @pytest.mark.no_test_domain
    def test_fallback_when_trace_retention_is_invalid(self):
        """Engine uses default retention when trace_retention_days is not a valid int."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        domain.config["observatory"] = {"trace_retention_days": "not-a-number"}

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            assert engine.emitter._retention_ms == 7 * 86_400_000

    @pytest.mark.no_test_domain
    def test_fallback_when_config_get_raises_attribute_error(self):
        """Engine uses default retention when config.get raises AttributeError."""
        from unittest.mock import patch, PropertyMock

        domain = Domain(name="Test")
        domain.init(traverse=False)
        # Replace config with a mock that raises AttributeError on .get()
        original_config = domain.config
        mock_config = MagicMock()
        mock_config.get.side_effect = AttributeError("broken")
        # Restore subscriptions and broker lookups to avoid secondary failures
        mock_config.__getitem__ = original_config.__getitem__
        mock_config.__contains__ = original_config.__contains__
        domain.config = mock_config

        with domain.domain_context():
            with patch.object(
                type(domain),
                "has_outbox",
                new_callable=PropertyMock,
                return_value=False,
            ):
                engine = Engine(domain, test_mode=True)
                assert engine.emitter._retention_ms == 7 * 86_400_000


# ---------------------------------------------------------------------------
# Engine startup with outbox configuration
# ---------------------------------------------------------------------------
class TestEngineOutboxValidation:
    @pytest.mark.no_test_domain
    def test_engine_starts_normally_without_outbox(self):
        """Engine should start when outbox is not enabled (event_store mode)."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            assert len(engine._outbox_processors) == 0

    @pytest.mark.no_test_domain
    def test_engine_starts_normally_with_outbox_and_tables(self):
        """Engine should start when outbox is enabled and repos are initialised."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            engine = Engine(domain, test_mode=True)
            assert len(engine._outbox_processors) > 0

    @pytest.mark.no_test_domain
    def test_engine_raises_when_outbox_table_missing(self):
        """Engine should raise ConfigurationError when outbox DAO is not accessible."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            # Sabotage the outbox repo to simulate missing table
            for provider_name, outbox_repo in domain._outbox_repos.items():
                original_dao = type(outbox_repo)._dao
                type(outbox_repo)._dao = property(
                    lambda self: (_ for _ in ()).throw(Exception("table not found"))
                )

                try:
                    with pytest.raises(
                        ConfigurationError,
                        match="Outbox table not found",
                    ):
                        Engine(domain, test_mode=True)
                finally:
                    type(outbox_repo)._dao = original_dao
