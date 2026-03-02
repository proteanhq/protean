"""Tests for subscription meta options on Projectors.

Gap 4: Projectors now support subscription_type, subscription_profile,
and subscription_config meta options, bringing parity with event handlers
and process managers.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.fields import Identifier, String
from protean.utils.mixins import handle


class Order(BaseAggregate):
    name: String(max_length=50)


class OrderPlaced(BaseEvent):
    order_id: Identifier(identifier=True)
    name: String()


class OrderSummary(BaseProjection):
    order_id: Identifier(identifier=True)
    name: String(max_length=50)


class OrderProjector(BaseProjector):
    @handle(OrderPlaced)
    def on_order_placed(self, event):
        pass


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(OrderSummary)
    test_domain.register(
        OrderProjector,
        projector_for=OrderSummary,
        aggregates=[Order],
    )
    test_domain.init(traverse=False)


class TestDefaultSubscriptionMeta:
    def test_default_subscription_type_is_none(self):
        assert OrderProjector.meta_.subscription_type is None

    def test_default_subscription_profile_is_none(self):
        assert OrderProjector.meta_.subscription_profile is None

    def test_default_subscription_config_is_empty_dict(self):
        assert OrderProjector.meta_.subscription_config == {}


class TestSubscriptionMetaViaDecorator:
    def test_subscription_type_via_decorator(self, test_domain):
        @test_domain.projector(
            projector_for=OrderSummary,
            aggregates=[Order],
            subscription_type="stream",
        )
        class StreamProjector(BaseProjector):
            @handle(OrderPlaced)
            def on_order_placed(self, event):
                pass

        assert StreamProjector.meta_.subscription_type == "stream"

    def test_subscription_profile_via_decorator(self, test_domain):
        @test_domain.projector(
            projector_for=OrderSummary,
            aggregates=[Order],
            subscription_profile="fast",
        )
        class FastProjector(BaseProjector):
            @handle(OrderPlaced)
            def on_order_placed(self, event):
                pass

        assert FastProjector.meta_.subscription_profile == "fast"

    def test_subscription_config_via_decorator(self, test_domain):
        @test_domain.projector(
            projector_for=OrderSummary,
            aggregates=[Order],
            subscription_config={"batch_size": 100},
        )
        class ConfiguredProjector(BaseProjector):
            @handle(OrderPlaced)
            def on_order_placed(self, event):
                pass

        assert ConfiguredProjector.meta_.subscription_config == {"batch_size": 100}


class TestSubscriptionMetaViaRegister:
    def test_subscription_type_via_register(self, test_domain):
        class RegProjector(BaseProjector):
            @handle(OrderPlaced)
            def on_order_placed(self, event):
                pass

        test_domain.register(
            RegProjector,
            projector_for=OrderSummary,
            aggregates=[Order],
            subscription_type="event_store",
        )
        assert RegProjector.meta_.subscription_type == "event_store"

    def test_subscription_profile_via_register(self, test_domain):
        class RegProjector2(BaseProjector):
            @handle(OrderPlaced)
            def on_order_placed(self, event):
                pass

        test_domain.register(
            RegProjector2,
            projector_for=OrderSummary,
            aggregates=[Order],
            subscription_profile="backfill",
        )
        assert RegProjector2.meta_.subscription_profile == "backfill"

    def test_subscription_config_via_register(self, test_domain):
        class RegProjector3(BaseProjector):
            @handle(OrderPlaced)
            def on_order_placed(self, event):
                pass

        test_domain.register(
            RegProjector3,
            projector_for=OrderSummary,
            aggregates=[Order],
            subscription_config={"max_retries": 3},
        )
        assert RegProjector3.meta_.subscription_config == {"max_retries": 3}
