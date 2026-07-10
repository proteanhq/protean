"""OTel scrape tests for the projection staleness gauge.

Verifies that ``protean.projection.staleness_seconds`` is registered and emits
observations when the metrics are scraped with telemetry enabled. Mirrors
``test_subscription_otel_metrics.py``.
"""

from datetime import UTC, datetime

import pytest
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.fields import Float, Identifier, String
from protean.server.observatory.metrics import (
    _register_infrastructure_gauges,
    _scrape_cache,
)
from protean.utils import fqn


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()
    name = String()


class User(BaseAggregate):
    email = String()
    name = String()


class Balances(BaseProjection):
    user_id = Identifier(identifier=True)
    name = String()
    balance = Float()


class BalancesProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        pass


class Tokens(BaseProjection):
    token_id = Identifier(identifier=True)


class TokensProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Balances)
    test_domain.register(BalancesProjector, projector_for=Balances, aggregates=[User])
    # A second projection with no position written -> staleness is None, exercising
    # the gauge callback's skip branch alongside Balances (which emits).
    test_domain.register(Tokens)
    test_domain.register(TokensProjector, projector_for=Tokens, aggregates=[User])
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def clear_scrape_cache():
    _scrape_cache.clear()
    yield
    _scrape_cache.clear()


def _init_telemetry_in_memory(domain):
    """Attach an in-memory OTel meter provider to the domain."""
    resource = Resource.create({"service.name": domain.normalized_name})
    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True
    return metric_reader


def _get_metric(metric_reader, name: str):
    data = metric_reader.get_metrics_data()
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    return metric
    return None


def _seed_caught_up(test_domain):
    with test_domain.domain_context():
        store = test_domain.event_store.store
        category = BalancesProjector.meta_.stream_categories[0]
        for i in range(3):
            store._write(f"{category}-{i}", "Registered", {"user_id": str(i)})
        head = store.stream_head_position(category)
        store._write(
            f"position-{fqn(BalancesProjector)}-{category}",
            "Read",
            {"position": head},
            metadata={"headers": {"time": datetime.now(UTC).isoformat()}},
        )


def test_staleness_gauge_emits_on_scrape(test_domain):
    """Scraping with telemetry on runs the gauge callback and yields the metric."""
    _seed_caught_up(test_domain)
    metric_reader = _init_telemetry_in_memory(test_domain)

    _register_infrastructure_gauges([test_domain])

    metric = _get_metric(metric_reader, "protean.projection.staleness_seconds")
    assert metric is not None

    points = list(metric.data.data_points)
    assert any(p.attributes.get("projection") == "Balances" for p in points)
    # Caught-up projection reports zero staleness.
    balances_point = next(
        p for p in points if p.attributes.get("projection") == "Balances"
    )
    assert balances_point.value == 0
