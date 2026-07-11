"""Domain models, Hypothesis strategies, and invariant helpers backing the
serialization round-trip property suite (:issue:`#1201`).

The suite pins the contract that ``to_dict()`` (``S``) and reconstruction via
``Type(**data)`` (``D``) are inverses. Equality means different things per
element kind, so the invariant asserted differs:

* **Value objects** use *value* equality (``__eq__`` compares ``to_dict()``),
  so the strongest form holds directly::

      D(S(x)) == x

* **Entities and aggregates** use *identity* equality (``__eq__`` compares the
  surrogate id). Object equality alone would be vacuous — it ignores every
  non-identity field — so the suite asserts **serializer idempotence** on the
  full dict, which does check every field survives::

      S(D(S(x))) == S(x)

* **Events and commands** also use identity equality, and reconstruction
  rebuilds volatile ``_metadata`` (fresh timestamps/versions). The suite
  asserts **payload idempotence** (idempotence with ``_metadata`` excluded)
  plus object equality.

The models below exercise every serializable field type in
``protean.fields.__all__``. ``Auto`` is covered as the auto-generated surrogate
identity of the entity/aggregate models (its ``id`` value is in ``to_dict()``
and pinned by the idempotence tests). Excluded: ``Reference`` (navigation, not
data), ``Method`` (behavior), ``Nested`` (schema-only), and ``ValueObjectList``
— a legacy raw ``Field`` that pydantic-based elements reject (it predates the
``FieldSpec`` serialization path these tests cover).
"""

from __future__ import annotations

from datetime import UTC, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

from protean.domain import Domain
from protean.fields import (
    Boolean,
    Date,
    DateTime,
    Dict,
    Float,
    HasMany,
    HasOne,
    Identifier,
    Integer,
    List,
    Status,
    String,
    Text,
    ValueObject,
)
from protean.fields import (
    Decimal as DecimalField,
)

serialization_domain = Domain(name="Serialization")

# Applied per property test (not loaded as a global profile — that would mutate
# process-wide Hypothesis state from a sub-directory conftest). Domain-object
# construction has variable latency, so a wall-clock deadline would flake under
# parallel CI load; disable it and cap examples for a fast, stable suite.
roundtrip_settings = settings(
    deadline=None,
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)


class Priority(Enum):
    """Backing enum for the ``Status`` field."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------
@serialization_domain.value_object
class Money:
    amount = DecimalField()
    currency = String()


@serialization_domain.value_object
class Address:
    """Exercises a *nested* value object (``ValueObject`` inside a VO)."""

    street = String()
    city = String()
    money = ValueObject(Money)


@serialization_domain.value_object
class StockLevels:
    """All-*default* value object for the :issue:`#1078` regression: a falsy
    VO (every field at its default) is still *present*, not ``None``."""

    on_hand = Integer(default=0)
    reserved = Integer(default=0)


@serialization_domain.value_object
class Scalars:
    """One VO carrying every scalar/collection field type."""

    a_string = String()
    a_text = Text()
    an_int = Integer()
    a_float = Float()
    a_decimal = DecimalField()
    a_bool = Boolean()
    a_date = Date()
    a_datetime = DateTime()
    an_ident = Identifier()
    a_status = Status(Priority)
    a_str_list = List(content_type=String())
    an_int_list = List(content_type=Integer())
    a_dict = Dict()


# ---------------------------------------------------------------------------
# Entity / aggregate (with HasMany + HasOne associations)
# ---------------------------------------------------------------------------
@serialization_domain.entity(part_of="Cart")
class LineItem:
    product = String()
    qty = Integer()
    price = DecimalField()


@serialization_domain.entity(part_of="Cart")
class Coupon:
    code = String()
    percent = Integer()


@serialization_domain.aggregate
class Cart:
    label = String()
    opened_at = DateTime()
    money = ValueObject(Money)
    items = HasMany(LineItem)
    coupon = HasOne(Coupon)


@serialization_domain.aggregate
class Inventory:
    """Embeds an all-default VO (:issue:`#1078` regression)."""

    sku = String()
    levels = ValueObject(StockLevels)


# ---------------------------------------------------------------------------
# Event / command
# ---------------------------------------------------------------------------
@serialization_domain.event(part_of="Cart")
class CartOpened:
    label = String()
    opened_at = DateTime()
    money = ValueObject(Money)


@serialization_domain.command(part_of="Cart")
class OpenCart:
    label = String()
    opened_at = DateTime()


serialization_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Value strategies — one per serializable field type.
# ---------------------------------------------------------------------------
def optional(strategy: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """A field left unset (``None``) must round-trip as cleanly as one set."""

    return st.none() | strategy


# ``String`` defaults to ``max_length=255``; stay well under it.
strings = st.text(max_size=64)
# ``Text`` has no length cap.
texts = st.text(max_size=256)
integers = st.integers(min_value=-(10**12), max_value=10**12)
# NaN breaks equality (NaN != NaN); ``inf`` is not a meaningful stored value.
floats = st.floats(allow_nan=False, allow_infinity=False, width=64)
# Decimals are string-encoded, so any finite decimal round-trips exactly.
decimals = st.decimals(
    allow_nan=False,
    allow_infinity=False,
    min_value=Decimal("-1e15"),
    max_value=Decimal("1e15"),
)
booleans = st.booleans()
dates = st.dates()
# Cover naive plus a spread of fixed UTC offsets (not just UTC), so non-UTC
# offsets exercise the isoformat/round-trip path. Fixed offsets (rather than
# named ``st.timezones()`` zones) keep the suite deterministic and free of a
# ``tzdata`` dependency, while still varying the serialized offset.
timezones = st.sampled_from(
    [
        None,
        UTC,
        timezone(timedelta(hours=5, minutes=30)),  # +05:30
        timezone(timedelta(hours=-8)),  # -08:00
        timezone(timedelta(hours=13)),  # +13:00
    ]
)
datetimes = st.datetimes(timezones=timezones)
identifiers = st.uuids().map(str)
statuses = st.sampled_from([p.value for p in Priority])
string_lists = st.lists(strings, max_size=5)
int_lists = st.lists(integers, max_size=5)
dicts = st.dictionaries(strings, st.one_of(integers, strings, booleans), max_size=5)


# ---------------------------------------------------------------------------
# Object strategies — build populated domain instances.
# ---------------------------------------------------------------------------
@st.composite
def money_st(draw: st.DrawFn) -> Money:
    return Money(amount=draw(optional(decimals)), currency=draw(optional(strings)))


@st.composite
def address_st(draw: st.DrawFn) -> Address:
    return Address(
        street=draw(optional(strings)),
        city=draw(optional(strings)),
        money=draw(optional(money_st())),
    )


@st.composite
def scalars_st(draw: st.DrawFn) -> Scalars:
    return Scalars(
        a_string=draw(optional(strings)),
        a_text=draw(optional(texts)),
        an_int=draw(optional(integers)),
        a_float=draw(optional(floats)),
        a_decimal=draw(optional(decimals)),
        a_bool=draw(optional(booleans)),
        a_date=draw(optional(dates)),
        a_datetime=draw(optional(datetimes)),
        an_ident=draw(optional(identifiers)),
        a_status=draw(optional(statuses)),
        # List/Dict fields reject ``None`` (they default to empty), so they are
        # drawn directly — an empty list/dict already covers the "unset" case.
        a_str_list=draw(string_lists),
        an_int_list=draw(int_lists),
        a_dict=draw(dicts),
    )


@st.composite
def line_item_st(draw: st.DrawFn) -> LineItem:
    return LineItem(
        product=draw(optional(strings)),
        qty=draw(optional(integers)),
        price=draw(optional(decimals)),
    )


@st.composite
def coupon_st(draw: st.DrawFn) -> Coupon:
    return Coupon(code=draw(optional(strings)), percent=draw(optional(integers)))


@st.composite
def cart_st(draw: st.DrawFn) -> Cart:
    return Cart(
        label=draw(optional(strings)),
        opened_at=draw(optional(datetimes)),
        money=draw(optional(money_st())),
        items=draw(st.lists(line_item_st(), max_size=4)),
        coupon=draw(optional(coupon_st())),
    )


@st.composite
def cart_opened_st(draw: st.DrawFn) -> CartOpened:
    return CartOpened(
        label=draw(optional(strings)),
        opened_at=draw(optional(datetimes)),
        money=draw(optional(money_st())),
    )


@st.composite
def open_cart_st(draw: st.DrawFn) -> OpenCart:
    return OpenCart(
        label=draw(optional(strings)),
        opened_at=draw(optional(datetimes)),
    )


# ---------------------------------------------------------------------------
# Invariant helpers — the three round-trip contracts.
# ---------------------------------------------------------------------------
def _payload(data: dict[str, Any]) -> dict[str, Any]:
    """The schema fields only, excluding volatile message ``_metadata``."""

    return {k: v for k, v in data.items() if k != "_metadata"}


def assert_value_object_roundtrip(vo: Any) -> None:
    """VO: ``D(S(x)) == x`` (value equality checks every field)."""

    serialized = vo.to_dict()
    assert type(vo)(**serialized) == vo


def assert_entity_roundtrip(obj: Any) -> None:
    """Entity/aggregate: serializer idempotence ``S(D(S(x))) == S(x)``."""

    serialized = obj.to_dict()
    rebuilt = type(obj)(**serialized)
    assert rebuilt.to_dict() == serialized
    # Identity equality holds too (id survives the round-trip).
    assert rebuilt == obj


def assert_message_roundtrip(msg: Any) -> None:
    """Event/command: payload idempotence.

    ``_metadata`` is rebuilt on reconstruction (fresh timestamps/versions) and,
    for a message constructed directly rather than raised through an aggregate,
    its ``headers.id`` is ``None`` — so ``rebuilt == msg`` (event/command
    equality compares that id) would assert ``None == None`` and pass
    vacuously. The meaningful invariant is that every schema payload field
    survives the round-trip byte-for-byte.
    """

    serialized = msg.to_dict()
    rebuilt = type(msg)(**serialized)
    assert _payload(rebuilt.to_dict()) == _payload(serialized)
