"""The engine runs outbox processors only for providers an aggregate is stored in.

The default config always defines a ``memory`` provider. The unit of work writes
outbox rows only to the providers of the aggregates it persists, so a provider
no aggregate names never receives a row. The engine and the status collector
both skip such providers, and they must agree on the set.
"""

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from protean import Engine
from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server.subscription_status import (
    _collect_outbox_statuses,
    _outbox_processor_names,
)
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus, _outbox_provider_names


def _domain(**config_overrides) -> Domain:
    domain = Domain(name="OutboxProviders")
    domain.config["server"]["default_subscription_type"] = "stream"
    for key, value in config_overrides.items():
        domain.config[key] = value
    return domain


def _aggregate(domain: Domain, name: str, **options) -> type[BaseAggregate]:
    cls = type(name, (BaseAggregate,), {"name": String()})
    domain.register(cls, **options)
    return cls


def _engine_processor_names(domain: Domain) -> set[str]:
    domain.init(traverse=False)
    with domain.domain_context():
        domain.setup_database()
        engine = Engine(domain, test_mode=True)
        return set(engine._outbox_processors)


def _with_global_broker(domain: Domain) -> Domain:
    domain.config["brokers"]["global"] = {"provider": "inline"}
    domain.config["outbox"] = {"external_brokers": ["global"]}
    return domain


@pytest.mark.no_test_domain
class TestEngineProcessorsFollowAggregateProviders:
    def test_aggregates_only_on_default_get_only_default_processors(self):
        domain = _with_global_broker(_domain())
        _aggregate(domain, "Order")

        assert _engine_processor_names(domain) == {
            "outbox-processor-default-to-default",
            "outbox-processor-default-to-global-external",
        }

    def test_status_rows_name_exactly_the_engine_processors(self):
        domain = _with_global_broker(_domain())
        _aggregate(domain, "Order")

        engine_names = _engine_processor_names(domain)
        status_names = [name for name, *_ in _outbox_processor_names(domain)]

        assert len(status_names) == len(engine_names) == 2
        assert set(status_names) == engine_names

    def test_an_aggregate_on_memory_gets_memory_processors(self):
        domain = _with_global_broker(_domain())
        _aggregate(domain, "Order")
        _aggregate(domain, "Cart", provider="memory")

        assert _engine_processor_names(domain) == {
            "outbox-processor-default-to-default",
            "outbox-processor-memory-to-default",
            "outbox-processor-default-to-global-external",
            "outbox-processor-memory-to-global-external",
        }

    def test_an_event_sourced_aggregate_alone_gets_a_processor(self):
        domain = _domain()
        _aggregate(domain, "Account", event_sourced=True)

        assert _engine_processor_names(domain) == {
            "outbox-processor-default-to-default"
        }

    def test_the_memory_event_store_record_does_not_count(self):
        domain = _domain(event_store={"provider": "memory"})
        _aggregate(domain, "Order")

        names = _engine_processor_names(domain)

        # Internal aggregates stored in `memory`: the event store's
        # MemoryMessage, plus the per-provider outbox clone
        internal_on_memory = [
            record.cls.__name__
            for record in domain.registry._elements["AGGREGATE"].values()
            if record.internal and record.cls.meta_.provider == "memory"
        ]
        assert "MemoryMessage" in internal_on_memory
        assert names == {"outbox-processor-default-to-default"}
        assert not any("-memory-" in name for name in names)

    def test_an_unmanaged_provider_gets_no_processor(self):
        domain = _with_global_broker(_domain())
        domain.config["databases"]["readonly"] = {
            "provider": "memory",
            "managed": False,
        }
        _aggregate(domain, "Order")
        _aggregate(domain, "Report", provider="readonly")

        names = _engine_processor_names(domain)

        assert names == {
            "outbox-processor-default-to-default",
            "outbox-processor-default-to-global-external",
        }

    def test_a_managed_provider_no_aggregate_names_gets_no_processor(self):
        domain = _domain()
        domain.config["databases"]["secondary"] = {"provider": "memory"}
        _aggregate(domain, "Order")

        names = _engine_processor_names(domain)

        assert names == {"outbox-processor-default-to-default"}
        assert [p for _, p, _, _ in _outbox_processor_names(domain)] == ["default"]
        assert [status.name for status in _collect_outbox_statuses(domain)] == [
            "outbox-processor-default-to-default"
        ]

    def test_an_abstract_aggregate_does_not_count(self):
        domain = _domain()
        domain.config["databases"]["archive"] = {"provider": "memory"}
        base = _aggregate(domain, "Base", abstract=True, provider="archive")
        order = type("Order", (base,), {})
        domain.register(order)

        assert order.meta_.provider == "default"
        assert _engine_processor_names(domain) == {
            "outbox-processor-default-to-default"
        }
        assert _outbox_processor_names(domain)[0][1] == "default"
        assert len(_outbox_processor_names(domain)) == 1

    def test_no_aggregates_means_no_processors_and_no_status_rows(self):
        domain = _with_global_broker(_domain())

        assert _engine_processor_names(domain) == set()
        assert _outbox_processor_names(domain) == []
        assert _collect_outbox_statuses(domain) == []


@pytest.mark.no_test_domain
class TestOutboxProviderNames:
    def test_order_follows_the_configured_providers(self):
        domain = _domain()
        domain.config["databases"]["zeta"] = {"provider": "memory"}
        domain.config["databases"]["alpha"] = {"provider": "memory"}
        # Registered in the reverse of config order
        _aggregate(domain, "Alpha", provider="alpha")
        _aggregate(domain, "Zeta", provider="zeta")
        _aggregate(domain, "Order")
        domain.init(traverse=False)

        configured = [n for n in domain.providers if n in {"default", "zeta", "alpha"}]
        assert configured == ["default", "zeta", "alpha"]
        assert _outbox_provider_names(domain) == configured

    def test_projections_do_not_count(self):
        domain = _domain()
        domain.config["databases"]["reports"] = {"provider": "memory"}
        _aggregate(domain, "Order")

        class Summary(BaseProjection):
            summary_id = Identifier(identifier=True)

        domain.register(Summary, provider="reports")
        domain.init(traverse=False)

        assert _outbox_provider_names(domain) == ["default"]


@pytest.mark.no_test_domain
class TestLeftoverRowsOnASkippedProvider:
    """A provider's outbox can hold rows from before its last aggregate moved away."""

    def _domain_with_secondary(self) -> Domain:
        domain = _domain()
        domain.config["databases"]["secondary"] = {"provider": "memory"}
        _aggregate(domain, "Order")
        domain.init(traverse=False)
        return domain

    def _save_row(self, domain: Domain, status: OutboxStatus) -> None:
        row = Outbox.create_message(
            message_id="msg-1",
            stream_name="test::order-1",
            message_type="Test.OrderPlaced.v1",
            data={},
            metadata=Metadata(
                headers=MessageHeaders(
                    id="msg-1",
                    type="Test.OrderPlaced.v1",
                    time=datetime.now(UTC),
                    stream="test::order-1",
                ),
                domain=DomainMeta(fqn="test.OrderPlaced", kind="event"),
            ),
        )
        row.status = status.value
        domain._get_outbox_repo("secondary").add(row)

    @pytest.mark.parametrize(
        "status",
        [
            OutboxStatus.PENDING,
            OutboxStatus.PROCESSING,
            OutboxStatus.FAILED,
            OutboxStatus.ABANDONED,
        ],
    )
    def test_unpublished_rows_log_a_warning(self, status, caplog):
        domain = self._domain_with_secondary()
        with domain.domain_context():
            domain.setup_database()
            self._save_row(domain, status)
            with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
                engine = Engine(domain, test_mode=True)

        assert set(engine._outbox_processors) == {"outbox-processor-default-to-default"}
        warnings = [
            r for r in caplog.records if r.msg == "engine.outbox_rows_without_processor"
        ]
        assert len(warnings) == 1
        assert warnings[0].provider == "secondary"
        assert warnings[0].unpublished == 1

    def test_published_rows_log_no_warning(self, caplog):
        domain = self._domain_with_secondary()
        with domain.domain_context():
            domain.setup_database()
            self._save_row(domain, OutboxStatus.PUBLISHED)
            with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
                Engine(domain, test_mode=True)

        assert not [
            r for r in caplog.records if r.msg == "engine.outbox_rows_without_processor"
        ]

    def test_failed_probe_logs_and_engine_still_starts(self, caplog):
        domain = self._domain_with_secondary()
        with domain.domain_context():
            domain.setup_database()
            broken_repo = MagicMock()
            broken_repo._dao.query.filter.return_value.count.side_effect = RuntimeError(
                "database unavailable"
            )

            with (
                patch.dict(domain._outbox_repos, {"secondary": broken_repo}),
                caplog.at_level(logging.WARNING, logger="protean.server.engine"),
            ):
                engine = Engine(domain, test_mode=True)

        assert set(engine._outbox_processors) == {"outbox-processor-default-to-default"}
        failures = [
            r for r in caplog.records if r.msg == "engine.outbox_leftover_probe_failed"
        ]
        assert len(failures) == 1
        assert failures[0].provider == "secondary"
