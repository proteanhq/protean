"""The ``version=`` decorator option is a peer of the ``__version__`` class
attribute: both declare an event's schema version, both feed the ``vN`` type
string, and declaring the version *both* ways is an error.

This is regression coverage — ``version=`` was silently ignored because
``__version__`` was resolved in ``__init_subclass__`` (at class creation),
before the decorator populated ``meta_``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils.eventing import Message


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)


class TestVersionOption:
    def test_version_option_sets_version(self, test_domain):
        """`version=N` sets `__version__` — the bug this fixes."""

        @test_domain.event(part_of=Order, version=3)
        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        assert OrderPlaced.__version__ == 3

    def test_version_option_via_register(self, test_domain):
        """`version=N` also works through the `register()` entry point."""

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(OrderPlaced, part_of=Order, version=2)

        assert OrderPlaced.__version__ == 2

    def test_version_option_on_plain_class(self, test_domain):
        """`version=N` also works for a plain class that does not subclass
        `BaseEvent` — the recreation path in `_derive_element_class`. (Every
        other test here uses the mutate path — the one the bug broke — so this
        guards both branches in one file.)"""

        @test_domain.event(part_of=Order, version=3)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        assert OrderPlaced.__version__ == 3

    def test_version_option_feeds_type_string(self, test_domain):
        """The `vN` in `__type__` is derived from the resolved version."""

        @test_domain.event(part_of=Order, version=4)
        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.init(traverse=False)

        assert OrderPlaced.__type__ == "Test.OrderPlaced.v4"

    def test_class_attribute_still_works(self, test_domain):
        """The `__version__ = N` class-attribute form is unchanged."""

        @test_domain.event(part_of=Order)
        class OrderPlaced(BaseEvent):
            __version__ = 5
            order_id = Identifier(identifier=True)

        assert OrderPlaced.__version__ == 5

    def test_default_version_is_one(self, test_domain):
        """Neither form declared → version defaults to 1."""

        @test_domain.event(part_of=Order)
        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        assert OrderPlaced.__version__ == 1

    def test_version_option_reflected_in_instance_metadata(self, test_domain):
        """An instance built from a `version=`-declared event carries the
        version in its metadata — parity with the `__version__` form."""

        @test_domain.event(part_of=Order, version=6)
        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.init(traverse=False)

        event = OrderPlaced(order_id="o1")
        assert event._metadata.domain.version == 6


class TestVersionOptionRejected:
    def test_both_forms_raise(self, test_domain):
        """Declaring the version twice is an error (the guard now fires)."""

        with pytest.raises(IncorrectUsageError, match="declares its version twice"):

            @test_domain.event(part_of=Order, version=2)
            class OrderPlaced(BaseEvent):
                __version__ = 2
                order_id = Identifier(identifier=True)

    def test_both_forms_raise_via_register(self, test_domain):
        """Same rejection through the `register()` entry point."""

        class OrderPlaced(BaseEvent):
            __version__ = 2
            order_id = Identifier(identifier=True)

        with pytest.raises(IncorrectUsageError, match="declares its version twice"):
            test_domain.register(OrderPlaced, part_of=Order, version=2)

    @pytest.mark.parametrize("bad", [0, -1, "3", 1.0])
    def test_invalid_version_option_raises(self, test_domain, bad):
        """`version=` must be a positive integer."""

        with pytest.raises(IncorrectUsageError, match="must be a positive integer"):

            @test_domain.event(part_of=Order, version=bad)
            class OrderPlaced(BaseEvent):
                order_id = Identifier(identifier=True)

    def test_boolean_version_option_rejected(self, test_domain):
        """`bool` is a subclass of `int` but is never a valid version."""

        with pytest.raises(IncorrectUsageError, match="must be a positive integer"):

            @test_domain.event(part_of=Order, version=True)
            class OrderPlaced(BaseEvent):
                order_id = Identifier(identifier=True)

    @pytest.mark.parametrize("bad", [0, -1, True])
    def test_invalid_class_attribute_still_rejected(self, test_domain, bad):
        """The class-attribute form is validated with the same rules."""

        with pytest.raises(IncorrectUsageError, match="must be a positive integer"):

            @test_domain.event(part_of=Order)
            class OrderPlaced(BaseEvent):
                __version__ = bad
                order_id = Identifier(identifier=True)


class TestVersionOptionWithUpcaster:
    def test_upcaster_chain_off_version_option_event(self, test_domain):
        """An upcaster chain keyed off a `version=`-declared event resolves —
        the `vN` type string and upcaster `to_version` line up."""

        @test_domain.event(part_of=Order, version=2)
        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)
            currency = String(default="USD")  # added in v2

        class UpcastOrderPlaced(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                # Write a value that differs from the field default so the
                # assertion below proves the upcaster actually ran (rather than
                # the field default masking a no-op).
                data.setdefault("currency", "EUR")
                return data

        test_domain.register(Order)
        test_domain.register(
            UpcastOrderPlaced,
            event_type=OrderPlaced,
            from_version=1,
            to_version=2,
        )
        test_domain.init(traverse=False)

        assert OrderPlaced.__type__ == "Test.OrderPlaced.v2"

        # A v1 payload lacks `currency`; the upcaster fills it.
        raw = {
            "data": {"order_id": "o1"},
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
        with test_domain.domain_context():
            event = Message.deserialize(raw, validate=False).to_domain_object()

        assert isinstance(event, OrderPlaced)
        # "EUR" (not the field default "USD") proves the upcaster ran.
        assert event.currency == "EUR"
