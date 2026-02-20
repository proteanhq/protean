"""Tests to increase coverage of process_manager.py and domain/__init__.py.

Covers utility methods (to_dict, __eq__, __hash__, __repr__, __str__),
edge cases (no matching handler, abstract PM, template dict init),
factory options (unprefixed stream categories, aggregates option),
and the default_factory / id_field paths in _load_or_create.
"""

import pytest
from uuid import uuid4

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.fields import Dict, Identifier, List, String
from protean.utils.mixins import handle

from .elements import (
    Order,
    OrderFulfillmentPM,
    OrderPlaced,
    Payment,
    PaymentConfirmed,
    PaymentFailed,
    Shipping,
    ShipmentDelivered,
)


@pytest.fixture(autouse=True)
def register_elements(test_domain, request):
    if "no_test_domain" in request.keywords:
        return
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(Payment)
    test_domain.register(PaymentConfirmed, part_of=Payment)
    test_domain.register(PaymentFailed, part_of=Payment)
    test_domain.register(Shipping)
    test_domain.register(ShipmentDelivered, part_of=Shipping)
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)


class TestToDict:
    def test_to_dict_returns_field_values(self, test_domain):
        """to_dict() should return all public fields as a dictionary."""
        order_id = str(uuid4())

        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )

        pm = OrderFulfillmentPM._load_or_create(order_id, is_start=False)
        result = pm.to_dict()

        assert isinstance(result, dict)
        assert result["order_id"] == order_id
        assert result["status"] == "awaiting_payment"

    def test_to_dict_on_new_instance(self, test_domain):
        """to_dict() should work on a freshly created PM."""
        pm = OrderFulfillmentPM._load_or_create("new-id", is_start=True)
        result = pm.to_dict()

        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "new"


class TestEquality:
    """Test __eq__ on process managers.

    OrderFulfillmentPM already subclasses BaseProcessManager so
    derive_element_class modifies it in-place without adding an auto id field.
    Without an explicit identifier field, __eq__ always returns False.
    """

    def test_pm_without_id_field_not_equal_to_same_data(self, test_domain):
        """Without an explicit identifier field, PMs are never equal (fallback)."""
        pm1 = OrderFulfillmentPM._load_or_create("order-1", is_start=True)
        pm2 = OrderFulfillmentPM._load_or_create("order-1", is_start=True)

        # __eq__ returns False when _ID_FIELD_NAME is not set (line 275-276)
        assert pm1 != pm2

    def test_pm_not_equal_to_different_type(self, test_domain):
        """A PM should not be equal to an object of a different type."""
        pm = OrderFulfillmentPM._load_or_create("order-1", is_start=True)
        # Covers line 272-273: type check
        assert pm != "not-a-pm"
        assert pm != 42
        assert pm != None  # noqa: E711

    @pytest.mark.no_test_domain
    def test_pm_with_identifier_field_equal(self):
        """PMs with an explicit identifier field should be equal when ids match."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class TaskAgg(BaseAggregate):
            name: String()

        class TaskEvt(BaseEvent):
            task_id: Identifier()

        class TaskPM(BaseProcessManager):
            task_id: Identifier(identifier=True)
            status: String(default="new")

            @handle(TaskEvt, start=True, correlate="task_id")
            def on_created(self, event: TaskEvt) -> None:
                self.task_id = event.task_id

        domain.register(TaskAgg)
        domain.register(TaskEvt, part_of=TaskAgg)
        domain.register(TaskPM, stream_categories=["testing::task_agg"])
        domain._initialize()
        domain.init(traverse=False)

        with domain.domain_context():
            pm1 = TaskPM._load_or_create("TASK-1", is_start=True)
            pm2 = TaskPM._load_or_create("TASK-1", is_start=True)

            # Covers line 277: identity-based equality
            assert pm1 == pm2

    @pytest.mark.no_test_domain
    def test_pm_with_identifier_field_unequal(self):
        """PMs with different identifier values should not be equal."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class TaskAgg2(BaseAggregate):
            name: String()

        class TaskEvt2(BaseEvent):
            task_id: Identifier()

        class TaskPM2(BaseProcessManager):
            task_id: Identifier(identifier=True)

            @handle(TaskEvt2, start=True, correlate="task_id")
            def on_created(self, event: TaskEvt2) -> None:
                self.task_id = event.task_id

        domain.register(TaskAgg2)
        domain.register(TaskEvt2, part_of=TaskAgg2)
        domain.register(TaskPM2, stream_categories=["testing::task_agg2"])
        domain._initialize()
        domain.init(traverse=False)

        with domain.domain_context():
            pm1 = TaskPM2._load_or_create("TASK-1", is_start=True)
            pm2 = TaskPM2._load_or_create("TASK-2", is_start=True)

            assert pm1 != pm2


class TestHash:
    def test_hash_without_id_field_uses_object_id(self, test_domain):
        """Without an explicit identifier field, hash falls back to id()."""
        pm1 = OrderFulfillmentPM._load_or_create("order-1", is_start=True)
        pm2 = OrderFulfillmentPM._load_or_create("order-1", is_start=True)

        # Covers line 281-282: fallback to id(self)
        assert hash(pm1) != hash(pm2)

    @pytest.mark.no_test_domain
    def test_hash_with_identifier_field(self):
        """PMs with an explicit identifier field should hash by id value."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class HashAgg(BaseAggregate):
            name: String()

        class HashEvt(BaseEvent):
            ref_id: Identifier()

        class HashPM(BaseProcessManager):
            ref_id: Identifier(identifier=True)

            @handle(HashEvt, start=True, correlate="ref_id")
            def on_created(self, event: HashEvt) -> None:
                self.ref_id = event.ref_id

        domain.register(HashAgg)
        domain.register(HashEvt, part_of=HashAgg)
        domain.register(HashPM, stream_categories=["testing::hash_agg"])
        domain._initialize()
        domain.init(traverse=False)

        with domain.domain_context():
            pm1 = HashPM._load_or_create("REF-1", is_start=True)
            pm2 = HashPM._load_or_create("REF-1", is_start=True)
            pm3 = HashPM._load_or_create("REF-2", is_start=True)

            # Covers line 283: hash(getattr(self, id_field_name))
            assert hash(pm1) == hash(pm2)
            assert hash(pm1) != hash(pm3)

    @pytest.mark.no_test_domain
    def test_pm_usable_in_set(self):
        """PMs with identifier fields should deduplicate in sets."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class SetAgg(BaseAggregate):
            name: String()

        class SetEvt(BaseEvent):
            ref_id: Identifier()

        class SetPM(BaseProcessManager):
            ref_id: Identifier(identifier=True)

            @handle(SetEvt, start=True, correlate="ref_id")
            def on_created(self, event: SetEvt) -> None:
                self.ref_id = event.ref_id

        domain.register(SetAgg)
        domain.register(SetEvt, part_of=SetAgg)
        domain.register(SetPM, stream_categories=["testing::set_agg"])
        domain._initialize()
        domain.init(traverse=False)

        with domain.domain_context():
            pm1 = SetPM._load_or_create("REF-1", is_start=True)
            pm2 = SetPM._load_or_create("REF-2", is_start=True)
            pm3 = SetPM._load_or_create("REF-1", is_start=True)

            pm_set = {pm1, pm2, pm3}
            assert len(pm_set) == 2


class TestReprStr:
    def test_repr_contains_class_name(self, test_domain):
        pm = OrderFulfillmentPM._load_or_create("order-1", is_start=True)
        r = repr(pm)

        assert "OrderFulfillmentPM" in r

    def test_str_contains_class_name(self, test_domain):
        pm = OrderFulfillmentPM._load_or_create("order-1", is_start=True)
        s = str(pm)

        assert "OrderFulfillmentPM" in s
        assert "object" in s


class TestNoMatchingHandler:
    def test_handle_returns_none_for_unknown_event(self, test_domain):
        """_handle should return None when no handler matches the event type."""

        # Create a standalone event with a __type__ not in the PM's handlers
        class UnrelatedEvent(BaseEvent):
            order_id: Identifier()

        # Manually set __type__ to simulate a registered event
        UnrelatedEvent.__type__ = "Test.UnrelatedEvent.v1"

        result = OrderFulfillmentPM._handle(UnrelatedEvent(order_id=str(uuid4())))

        assert result is None


class TestAbstractProcessManager:
    def test_abstract_pm_cannot_be_instantiated(self, test_domain):
        """An abstract process manager should raise NotSupportedError on instantiation."""

        class AbstractPM(BaseProcessManager):
            some_field: String()

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_order(self, event: OrderPlaced) -> None:
                pass

        # Abstract flag is set via register(), not Meta inner class
        test_domain.register(AbstractPM, abstract=True)

        with pytest.raises(NotSupportedError, match="marked abstract"):
            AbstractPM(some_field="test")


class TestTemplateDictInit:
    def test_init_with_template_dict(self, test_domain):
        """PM should support positional dict argument for initialization."""
        pm = OrderFulfillmentPM(
            {"order_id": "ORD-1", "status": "test"},
            payment_id="PAY-1",
        )

        assert pm.order_id == "ORD-1"
        assert pm.status == "test"
        assert pm.payment_id == "PAY-1"

    def test_init_with_invalid_positional_arg(self):
        """Non-dict positional args should raise AssertionError."""
        with pytest.raises(AssertionError, match="must be a dict"):
            OrderFulfillmentPM("not-a-dict")


class TestDefaultFactory:
    """Test PM fields that use default_factory (e.g., List, Dict)."""

    @pytest.mark.no_test_domain
    def test_default_factory_field_in_load_or_create(self):
        """Fields with default_factory should be initialized correctly."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class FactoryAgg(BaseAggregate):
            name: String()

        class FactoryEvt(BaseEvent):
            task_id: Identifier()

        class FactoryPM(BaseProcessManager):
            task_id: Identifier()
            tags: List(content_type=String, default=list)
            metadata: Dict(default=dict)
            status: String(default="new")

            @handle(FactoryEvt, start=True, correlate="task_id")
            def on_created(self, event: FactoryEvt) -> None:
                self.task_id = event.task_id

        domain.register(FactoryAgg)
        domain.register(FactoryEvt, part_of=FactoryAgg)
        domain.register(FactoryPM, stream_categories=["testing::factory_agg"])
        domain._initialize()
        domain.init(traverse=False)

        with domain.domain_context():
            pm = FactoryPM._load_or_create("task-1", is_start=True)

            # default_factory fields should be initialized to their defaults
            assert pm.tags == []
            assert pm.metadata == {}
            assert pm.status == "new"


class TestIdFieldAssignment:
    @pytest.mark.no_test_domain
    def test_id_field_set_to_correlation_value(self):
        """When a PM has an explicit identifier, _load_or_create sets it to the
        correlation value."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class IdAgg(BaseAggregate):
            name: String()

        class IdEvt(BaseEvent):
            my_id: Identifier()

        class IdPM(BaseProcessManager):
            my_id: Identifier(identifier=True)
            status: String(default="new")

            @handle(IdEvt, start=True, correlate="my_id")
            def on_created(self, event: IdEvt) -> None:
                self.my_id = event.my_id

        domain.register(IdAgg)
        domain.register(IdEvt, part_of=IdAgg)
        domain.register(IdPM, stream_categories=["testing::id_agg"])
        domain._initialize()
        domain.init(traverse=False)

        with domain.domain_context():
            pm = IdPM._load_or_create("MY-123", is_start=True)

            # The explicit identifier field should be set to the correlation value
            assert pm.my_id == "MY-123"
            assert pm._correlation_value == "MY-123"

    def test_correlation_value_set_on_new_pm(self, test_domain):
        """_correlation_value should always be set on a new PM."""
        pm = OrderFulfillmentPM._load_or_create("ORD-456", is_start=True)

        assert pm._correlation_value == "ORD-456"


class TestFactoryStreamCategoryPrefixing:
    @pytest.mark.no_test_domain
    def test_unprefixed_stream_categories_get_domain_prefix(self):
        """Stream categories without '::' should be prefixed with domain name."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class SomeAggregate(BaseAggregate):
            name: String()

        class SomeEvent(BaseEvent):
            agg_id: Identifier()

        class SomePM(BaseProcessManager):
            agg_id: Identifier()

            @handle(SomeEvent, start=True, correlate="agg_id")
            def on_event(self, event: SomeEvent) -> None:
                self.agg_id = event.agg_id

        domain.register(SomeAggregate)
        domain.register(SomeEvent, part_of=SomeAggregate)
        # Use unprefixed stream categories
        domain.register(SomePM, stream_categories=["some_aggregate"])
        domain.init(traverse=False)

        # normalized_name for "Testing" is "testing"
        assert "testing::some_aggregate" in SomePM.meta_.stream_categories

    @pytest.mark.no_test_domain
    def test_already_prefixed_stream_categories_unchanged(self):
        """Stream categories with '::' should not be double-prefixed."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class SomeAggregate2(BaseAggregate):
            name: String()

        class SomeEvent2(BaseEvent):
            agg_id: Identifier()

        class SomePM2(BaseProcessManager):
            agg_id: Identifier()

            @handle(SomeEvent2, start=True, correlate="agg_id")
            def on_event(self, event: SomeEvent2) -> None:
                self.agg_id = event.agg_id

        domain.register(SomeAggregate2)
        domain.register(SomeEvent2, part_of=SomeAggregate2)
        domain.register(SomePM2, stream_categories=["custom::stream"])
        domain.init(traverse=False)

        assert "custom::stream" in SomePM2.meta_.stream_categories


class TestAggregatesOption:
    @pytest.mark.no_test_domain
    def test_aggregates_option_derives_stream_categories(self):
        """When aggregates is specified without stream_categories, categories should
        be inferred from the aggregates' stream categories."""
        from protean.domain import Domain

        domain = Domain(__file__, "Testing")

        class OrderAgg(BaseAggregate):
            name: String()

        class OrderEvt(BaseEvent):
            order_id: Identifier()

        class AggPM(BaseProcessManager):
            order_id: Identifier()

            @handle(OrderEvt, start=True, correlate="order_id")
            def on_order(self, event: OrderEvt) -> None:
                self.order_id = event.order_id

        domain.register(OrderAgg)
        domain.register(OrderEvt, part_of=OrderAgg)
        domain.register(AggPM, aggregates=[OrderAgg])
        domain.init(traverse=False)

        # Stream categories should be inferred from OrderAgg
        assert len(AggPM.meta_.stream_categories) > 0


class TestPersistTransitionWithoutInit:
    def test_persist_raises_when_no_transition_cls(self):
        """_persist_transition should raise ConfigurationError if domain.init()
        was not called (no transition event class)."""

        class UninitializedPM(BaseProcessManager):
            my_id: Identifier()

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_order(self, event: OrderPlaced) -> None:
                pass

        # _transition_event_cls is None because we never called domain.init()
        pm = UninitializedPM.__new__(UninitializedPM)
        object.__setattr__(pm, "__dict__", {"my_id": "test"})
        object.__setattr__(pm, "__pydantic_extra__", None)
        object.__setattr__(pm, "__pydantic_fields_set__", set())
        object.__setattr__(
            pm,
            "__pydantic_private__",
            {"_version": -1, "_is_complete": False, "_correlation_value": "test"},
        )

        with pytest.raises(ConfigurationError, match="no transition event class"):
            UninitializedPM._persist_transition(pm, "on_order")
