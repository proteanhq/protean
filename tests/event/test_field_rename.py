"""Field renames resolve old stored payloads and appear in IR.

A field declaring ``renamed_from`` loads a payload written under the old key
without an upcaster, and the rename metadata is emitted into the IR.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.fields import Identifier, String
from protean.utils import fqn as get_fqn
from protean.utils.eventing import Message


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)


class OrderPlaced(BaseEvent):
    order_id = Identifier(identifier=True)
    customer_name = String(renamed_from=["name", "cust"])


def _register(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.init(traverse=False)


def _raw(data: dict) -> dict:
    """A raw stored message dict for OrderPlaced."""
    return {
        "data": data,
        "metadata": {
            "headers": {
                "id": "m1",
                "type": "Test.OrderPlaced.v1",
                "time": "2025-01-01T00:00:00+00:00",
                "stream": "test::order-1",
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": "app.OrderPlaced",
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": "test::order",
                "version": 1,
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }


class TestRenameInIR:
    def test_renamed_from_emitted_into_ir_field(self, test_domain):
        _register(test_domain)
        ir = test_domain.to_ir()
        fields = ir["clusters"][get_fqn(Order)]["events"]
        placed = next(iter(fields.values()))
        assert placed["fields"]["customer_name"]["renamed_from"] == ["name", "cust"]

    def test_non_renamed_field_has_no_renamed_from_key(self, test_domain):
        _register(test_domain)
        ir = test_domain.to_ir()
        placed = next(iter(ir["clusters"][get_fqn(Order)]["events"].values()))
        assert "renamed_from" not in placed["fields"]["order_id"]


class TestRenameDeserialization:
    def test_old_key_loads_into_renamed_field(self, test_domain):
        _register(test_domain)
        with test_domain.domain_context():
            msg = Message.deserialize(
                _raw({"order_id": "o1", "name": "Alice"}), validate=False
            )
            event = msg.to_domain_object()
        assert isinstance(event, OrderPlaced)
        assert event.customer_name == "Alice"

    def test_second_alias_also_resolves(self, test_domain):
        _register(test_domain)
        with test_domain.domain_context():
            msg = Message.deserialize(
                _raw({"order_id": "o1", "cust": "Bob"}), validate=False
            )
            event = msg.to_domain_object()
        assert event.customer_name == "Bob"

    def test_current_name_wins_over_stale_alias(self, test_domain):
        _register(test_domain)
        with test_domain.domain_context():
            msg = Message.deserialize(
                _raw({"order_id": "o1", "customer_name": "Carol", "name": "STALE"}),
                validate=False,
            )
            event = msg.to_domain_object()
        assert event.customer_name == "Carol"

    def test_current_payload_deserializes_unchanged(self, test_domain):
        _register(test_domain)
        with test_domain.domain_context():
            msg = Message.deserialize(
                _raw({"order_id": "o1", "customer_name": "Dave"}), validate=False
            )
            event = msg.to_domain_object()
        assert event.customer_name == "Dave"


class TestResolveFieldAliasesHelper:
    def test_no_rename_returns_same_dict_object(self, test_domain):
        """Fast path: with no matching alias, the original dict is returned
        (not a copy) so the common case adds no allocation."""
        _register(test_domain)
        data = {"order_id": "o1", "customer_name": "Dave"}
        assert Message._resolve_field_aliases(OrderPlaced, data) is data

    def test_alias_resolution_does_not_mutate_input(self, test_domain):
        _register(test_domain)
        data = {"order_id": "o1", "name": "Alice"}
        resolved = Message._resolve_field_aliases(OrderPlaced, data)
        assert resolved == {"order_id": "o1", "customer_name": "Alice"}
        assert data == {"order_id": "o1", "name": "Alice"}  # untouched


class TestRenameEdgeCases:
    def test_alias_matching_a_live_field_does_not_clobber(self, test_domain):
        """An alias that is also a live field name is ignored, so the live
        field's value is never stolen."""

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class Placed(BaseEvent):
            order_id = Identifier(identifier=True)
            name = String()  # live field
            customer_name = String(renamed_from="name")  # alias shadows it

        test_domain.register(Order)
        test_domain.register(Placed, part_of=Order)
        test_domain.init(traverse=False)

        resolved = Message._resolve_field_aliases(
            Placed, {"order_id": "o1", "name": "Alice"}
        )
        assert resolved["name"] == "Alice"  # live field kept
        assert "customer_name" not in resolved  # not stolen

    def test_two_fields_sharing_an_alias_does_not_crash(self, test_domain):
        """Two fields declaring the same alias: the first claims the key and
        resolution does not raise ``KeyError``."""

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class Placed(BaseEvent):
            order_id = Identifier(identifier=True)
            first = String(renamed_from="old")
            second = String(renamed_from="old")

        test_domain.register(Order)
        test_domain.register(Placed, part_of=Order)
        test_domain.init(traverse=False)

        resolved = Message._resolve_field_aliases(
            Placed, {"order_id": "o1", "old": "X"}
        )
        assert resolved["first"] == "X"
        assert "old" not in resolved
        assert "second" not in resolved


class TestCommandRename:
    def test_command_resolves_alias(self, test_domain):
        """Commands share the ``to_domain_object`` path, so alias resolution
        applies to them too."""

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class PlaceOrder(BaseCommand):
            order_id = Identifier(identifier=True)
            customer_name = String(renamed_from="name")

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.init(traverse=False)

        resolved = Message._resolve_field_aliases(
            PlaceOrder, {"order_id": "o1", "name": "Alice"}
        )
        assert resolved == {"order_id": "o1", "customer_name": "Alice"}


class TestUpcasterAndRename:
    def test_upcaster_then_rename_compose(self, test_domain):
        """A v1 payload is upcast to the current schema first, then old keys are
        resolved onto renamed fields — both mechanisms compose."""

        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlacedV2(BaseEvent):
            __version__ = 2
            order_id = Identifier(identifier=True)
            customer_name = String(renamed_from="name")  # renamed since v1
            currency = String(default="USD")  # added in v2

        class UpcastOrderPlaced(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                data.setdefault("currency", "USD")
                return data

        test_domain.register(Order)
        test_domain.register(OrderPlacedV2, part_of=Order)
        test_domain.register(
            UpcastOrderPlaced,
            event_type=OrderPlacedV2,
            from_version=1,
            to_version=2,
        )
        test_domain.init(traverse=False)

        # A v1 payload: old `name` key, no `currency`.
        raw = {
            "data": {"order_id": "o1", "name": "Alice"},
            "metadata": {
                "headers": {
                    "id": "m1",
                    "type": "Test.OrderPlacedV2.v1",
                    "time": "2025-01-01T00:00:00+00:00",
                    "stream": "test::order-1",
                },
                "envelope": {"specversion": "1.0"},
                "domain": {
                    "fqn": "app.OrderPlacedV2",
                    "kind": "EVENT",
                    "origin_stream": None,
                    "stream_category": "test::order",
                    "version": 1,
                    "sequence_id": "0",
                    "asynchronous": True,
                },
            },
        }
        with test_domain.domain_context():
            event = Message.deserialize(raw, validate=False).to_domain_object()

        assert isinstance(event, OrderPlacedV2)
        assert event.customer_name == "Alice"  # rename resolved
        assert event.currency == "USD"  # upcaster filled default
