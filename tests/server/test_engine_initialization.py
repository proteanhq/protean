import asyncio
import logging
from unittest.mock import patch

import pytest

from protean import Engine
from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.fields import String


def _register_aggregate(domain, provider="default"):
    """Store one aggregate in *provider*.

    The engine runs outbox processors only for providers an aggregate is
    stored in, so a domain needs one before it has any processor to inspect.
    """

    # Distinct names per provider, because the registry keys elements by name
    record_cls = type(
        f"{provider.capitalize()}Record", (BaseAggregate,), {"name": String()}
    )
    domain.register(record_cls, provider=provider)


def test_engine_initialized_from_a_domain_object_owns_an_idle_loop(test_domain):
    engine = Engine(test_domain)
    assert engine.domain == test_domain
    assert engine.loop is not None
    assert isinstance(engine.loop, asyncio.SelectorEventLoop)
    assert engine.loop.is_running() is False
    assert engine.loop.is_closed() is False


# ---------------------------------------------------------------------------
# Observatory config fallback
# ---------------------------------------------------------------------------
class TestEngineObservatoryConfigFallback:
    """Test that Engine falls back to default trace_retention_days on bad config."""

    _MISSING = object()

    @pytest.mark.no_test_domain
    @pytest.mark.parametrize(
        "observatory_config",
        [
            pytest.param(_MISSING, id="observatory-config-missing"),
            pytest.param(
                {"trace_retention_days": "not-a-number"}, id="retention-not-an-int"
            ),
            pytest.param({"trace_retention_days": float("inf")}, id="retention-inf"),
            pytest.param("not-a-table", id="observatory-config-not-a-table"),
        ],
    )
    def test_falls_back_to_seven_days(self, observatory_config):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        if observatory_config is self._MISSING:
            domain.config.pop("observatory", None)
        else:
            domain.config["observatory"] = observatory_config

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            assert engine.emitter._persist is True
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
    def test_engine_raises_when_outbox_table_missing(self):
        """Engine should raise ConfigurationError when outbox DAO is not accessible."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            # Sabotage the outbox repo to simulate missing table
            for outbox_repo in domain._outbox_repos.values():
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


# ---------------------------------------------------------------------------
# Engine outbox processors skip unmanaged providers
# ---------------------------------------------------------------------------
class TestEngineOutboxSkipsUnmanagedProviders:
    @pytest.mark.no_test_domain
    def test_no_outbox_processor_for_unmanaged_provider(self):
        """Engine should not create outbox processors for unmanaged providers."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.config["databases"]["unmanaged"] = {
            "provider": "memory",
            "managed": False,
        }
        _register_aggregate(domain)
        _register_aggregate(domain, provider="unmanaged")
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            engine = Engine(domain, test_mode=True)

            # Only the default (managed) provider should have outbox processors
            assert set(engine._outbox_processors) == {
                "outbox-processor-default-to-default"
            }

    @pytest.mark.no_test_domain
    def test_outbox_processor_created_for_managed_provider(self):
        """Engine should create outbox processors for managed providers."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.config["databases"]["secondary"] = {
            "provider": "memory",
            "managed": True,
        }
        _register_aggregate(domain)
        _register_aggregate(domain, provider="secondary")
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            engine = Engine(domain, test_mode=True)

            assert set(engine._outbox_processors) == {
                "outbox-processor-default-to-default",
                "outbox-processor-secondary-to-default",
            }

    @pytest.mark.no_test_domain
    def test_external_outbox_processor_skips_unmanaged(self):
        """External outbox processors should also skip unmanaged providers."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.config["databases"]["unmanaged"] = {
            "provider": "memory",
            "managed": False,
        }
        # Configure a second broker as external
        domain.config["brokers"]["external_broker"] = {
            "provider": "inline",
        }
        domain.config["outbox"] = {
            "external_brokers": ["external_broker"],
        }
        _register_aggregate(domain)
        _register_aggregate(domain, provider="unmanaged")
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            engine = Engine(domain, test_mode=True)

            # Only the default (managed) provider gets primary and external processors
            assert set(engine._outbox_processors) == {
                "outbox-processor-default-to-default",
                "outbox-processor-default-to-external_broker-external",
            }


class TestEngineInitializationFailure:
    """The engine closes the event loop it opened when wiring then fails."""

    def test_loop_is_closed_when_wiring_raises(self, test_domain):
        # An outbox that names an unconfigured external broker fails wiring
        test_domain.config["enable_outbox"] = True
        test_domain.config["outbox"] = {"external_brokers": ["missing"]}

        loops = []
        real_new_event_loop = asyncio.new_event_loop

        def _tracked_new_event_loop():
            loop = real_new_event_loop()
            loops.append(loop)
            return loop

        # __init__ opens the loop before it wires anything, and the caller never
        # gets a reference to a half-built engine, so a failure past that point
        # would leak the loop unless __init__ closes it itself.
        with (
            patch(
                "protean.server.engine.asyncio.new_event_loop",
                side_effect=_tracked_new_event_loop,
            ),
            pytest.raises(ValueError, match="External broker 'missing'"),
        ):
            Engine(test_domain, test_mode=True)

        assert len(loops) == 1
        assert loops[0].is_closed() is True


class TestEngineDlqMaintenanceConfig:
    """DLQ upkeep is optional, so bad DLQ config never stops the engine."""

    def test_engine_starts_without_dlq_upkeep_when_dlq_config_is_not_a_table(
        self, test_domain, caplog
    ):
        test_domain.config["server"]["dlq"] = "on"

        with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
            engine = Engine(test_domain, test_mode=True)

        assert engine._dlq_maintenance is None
        assert any(
            r.message == "engine.dlq_maintenance_init_skipped" for r in caplog.records
        )
