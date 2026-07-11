"""Opt-in lenient deserialization of legacy payloads.

Strict `extra="forbid"` stays the default. Opt-in (config key or per-event
`lenient` option) drops fields no longer on the class and records them on the
message metadata; the current-name-wins alias resolution still runs
first, so a renamed old key is kept rather than dropped.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.domain.config import _default_config
from protean.exceptions import DeserializationError
from protean.fields import Identifier, String
from protean.utils.eventing import Message


def _raw(data: dict, type_string: str = "Test.OrderPlaced.v1", kind: str = "EVENT"):
    return {
        "data": data,
        "metadata": {
            "headers": {
                "id": "m1",
                "type": type_string,
                "time": "2025-01-01T00:00:00+00:00",
                "stream": "test::order-1",
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": "app.OrderPlaced",
                "kind": kind,
                "origin_stream": None,
                "stream_category": "test::order",
                "version": 1,
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }


def _load(test_domain, data):
    with test_domain.domain_context():
        return Message.deserialize(_raw(data), validate=False).to_domain_object()


class TestStrictDefault:
    def test_default_config_is_strict(self):
        assert _default_config()["lenient_deserialization"] is False

    def test_unknown_field_raises_by_default(self, test_domain):
        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)
            name = String()

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        with pytest.raises(DeserializationError):
            _load(test_domain, {"order_id": "1", "name": "A", "gone": "X"})


class TestLenientConfig:
    def _setup(self, test_domain, lenient):
        test_domain.config["lenient_deserialization"] = lenient

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)
            name = String()

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)
        return OrderPlaced

    def test_lenient_drops_unknown_and_records_them(self, test_domain):
        self._setup(test_domain, lenient=True)
        event = _load(
            test_domain, {"order_id": "1", "name": "A", "gone": "X", "old": "Y"}
        )
        assert event.name == "A"
        assert event._metadata.extensions["_dropped_fields"] == ["gone", "old"]

    def test_lenient_with_no_unknown_fields_records_nothing(self, test_domain):
        """Negative: the `_dropped_fields` key is absent when nothing is dropped."""
        self._setup(test_domain, lenient=True)
        event = _load(test_domain, {"order_id": "1", "name": "A"})
        assert "_dropped_fields" not in event._metadata.extensions

    def test_config_false_still_raises(self, test_domain):
        self._setup(test_domain, lenient=False)
        with pytest.raises(DeserializationError):
            _load(test_domain, {"order_id": "1", "name": "A", "gone": "X"})

    def test_all_unknown_fields_still_raises_on_required(self, test_domain):
        """Lenient mode drops unknowns but does not fabricate required fields:
        a payload of only unknown keys still fails required-field validation."""
        test_domain.config["lenient_deserialization"] = True

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)
            name = String(required=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        with pytest.raises(DeserializationError):
            _load(test_domain, {"gone": "X", "obsolete": "Y"})


class TestPerEventOverride:
    def _register(self, test_domain, config_lenient, event_lenient):
        test_domain.config["lenient_deserialization"] = config_lenient

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        opts = {} if event_lenient is None else {"lenient": event_lenient}

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)
            name = String()

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order, **opts)
        test_domain.init(traverse=False)

    def test_event_lenient_true_overrides_config_false(self, test_domain):
        self._register(test_domain, config_lenient=False, event_lenient=True)
        event = _load(test_domain, {"order_id": "1", "name": "A", "gone": "X"})
        assert event._metadata.extensions["_dropped_fields"] == ["gone"]

    def test_event_lenient_false_overrides_config_true(self, test_domain):
        self._register(test_domain, config_lenient=True, event_lenient=False)
        with pytest.raises(DeserializationError):
            _load(test_domain, {"order_id": "1", "name": "A", "gone": "X"})

    def test_default_option_is_none(self, test_domain):
        """The per-event `lenient` option defaults to None (defers to config)."""

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        assert OrderPlaced.meta_.lenient is None


class TestLenientWithRename:
    def test_alias_is_kept_only_truly_unknown_is_dropped(self, test_domain):
        """Alias resolution runs before the lenient drop, so a renamed
        old key loads into the new field and only genuinely-unknown keys drop."""
        test_domain.config["lenient_deserialization"] = True

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)
            customer_name = String(renamed_from="name")

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        event = _load(test_domain, {"order_id": "1", "name": "Alice", "gone": "X"})
        assert event.customer_name == "Alice"  # alias kept
        assert event._metadata.extensions["_dropped_fields"] == ["gone"]  # only unknown


class TestCommandParity:
    def test_command_lenient_deserialization(self, test_domain):
        test_domain.config["lenient_deserialization"] = True

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class PlaceOrder(BaseCommand):
            order_id = Identifier(identifier=True)
            name = String()

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            raw = _raw(
                {"order_id": "1", "name": "A", "gone": "X"},
                type_string="Test.PlaceOrder.v1",
                kind="COMMAND",
            )
            command = Message.deserialize(raw, validate=False).to_domain_object()
        assert command.name == "A"
        assert command._metadata.extensions["_dropped_fields"] == ["gone"]
