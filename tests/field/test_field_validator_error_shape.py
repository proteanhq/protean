"""Field validator errors have one shape on every field kind and path.

``ValidationError.messages`` is a plain ``dict[str, list[str]]``. A validator
that raises a dict has its keys merged under the field as dotted keys.
Construction reports every failing simple, ``ValueObject``, ``ValueObjectList``
and ``Reference`` field. Attribute assignment reports the field being set.
"""

from typing import Any

import pytest

from protean._deprecation import RemovedInProtean020Warning
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import (
    HasMany,
    Identifier,
    Reference,
    String,
    ValueObject,
    ValueObjectList,
)


def _contains_x(value: Any) -> bool:
    if isinstance(value, str):
        return "x" in value
    if isinstance(value, list):
        return any(_contains_x(item) for item in value)
    return _contains_x(getattr(value, "city", None) or getattr(value, "name", ""))


def no_x(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError("has x")


def no_x_dict(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError({"code": ["has x"]})


def no_x_nested(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError({"code": {"inner": ["m"]}})


def no_x_two(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError({"code": ["a", "b"]})


def no_x_list(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError(["m1", "m2"])


def no_x_coded(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError("has x", code="PRT-X")


def no_x_coded_again(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError("has x again", code="PRT-X")


def no_x_empty(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError({})


def no_x_dict_in_list(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError([{"k": ["m"]}, "plain"])


def never_fails(value: Any) -> None:
    return None


def no_x_with_error(value: Any) -> None:
    if _contains_x(value):
        raise ValidationError("raw message")


no_x_with_error.error = "override message"  # type: ignore[attr-defined]


class Addr(BaseValueObject):
    city = String()


class Target(BaseAggregate):
    name = String()


class Parent(BaseAggregate):
    title = String()


def _fields() -> dict[str, Any]:
    """Return a fresh set of field declarations for one owner class."""
    return {
        "s": String(validators=[no_x]),
        "t": String(validators=[no_x_dict]),
        "u": String(validators=[no_x_coded]),
        "w": String(validators=[never_fails]),
        "o": String(validators=[no_x_with_error]),
        "q": String(validators=[no_x_list]),
        "es": String(validators=[no_x_empty]),
        "e": ValueObject(Addr, validators=[no_x_empty]),
        "dl": ValueObject(Addr, validators=[no_x_dict_in_list]),
        "a": ValueObject(Addr, validators=[no_x]),
        "b": ValueObject(Addr, validators=[no_x_dict]),
        "n": ValueObject(Addr, validators=[no_x_nested]),
        "m": ValueObject(Addr, validators=[no_x_two]),
        "c": ValueObject(Addr, validators=[no_x_coded, no_x_coded_again]),
        "v": ValueObject(Addr, validators=[no_x_list]),
        "l": ValueObjectList(content_type=ValueObject(Addr), validators=[no_x]),
        "r": Reference(Target, validators=[no_x]),
    }


@pytest.fixture(params=["aggregate", "entity"])
def owner_cls(request, test_domain):
    test_domain.register(Addr)
    test_domain.register(Target)
    if request.param == "aggregate":
        cls = type("Owner", (BaseAggregate,), _fields())
        test_domain.register(cls)
    else:
        test_domain.register(Parent)
        cls = type("OwnerEntity", (BaseEntity,), _fields())
        test_domain.register(cls, part_of=Parent)
    test_domain.init(traverse=False)
    return cls


def _bad(name: str) -> Any:
    """Return a value that fails the ``x`` validator on field ``name``."""
    if name in ("a", "b", "n", "m", "c", "v", "e", "dl"):
        return Addr(city="x")
    if name == "l":
        return [Addr(city="x")]
    if name == "r":
        return Target(name="x")
    return "x"


# (fields set to a failing value, expected messages on create)
CASES = [
    (["s"], {"s": ["has x"]}),
    (["t"], {"t.code": ["has x"]}),
    (["a"], {"a": ["has x"]}),
    (["b"], {"b.code": ["has x"]}),
    (["n"], {"n.code.inner": ["m"]}),
    (["m"], {"m.code": ["a", "b"]}),
    (["q"], {"q": ["m1", "m2"]}),
    (["v"], {"v": ["m1", "m2"]}),
    (["es"], {"es": ["{}"]}),
    (["e"], {"e": ["{}"]}),
    (["dl"], {"dl.k": ["m"], "dl": ["plain"]}),
    (["o"], {"o": ["override message"]}),
    (["l"], {"l": ["has x"]}),
    (["r"], {"r": ["has x"]}),
    (["s", "a"], {"s": ["has x"], "a": ["has x"]}),
    (["a", "b"], {"a": ["has x"], "b.code": ["has x"]}),
]


@pytest.mark.parametrize("names,expected", CASES)
def test_create_reports_flat_messages(owner_cls, names, expected):
    with pytest.raises(ValidationError) as exc:
        owner_cls(**{name: _bad(name) for name in names})

    assert type(exc.value.messages) is dict
    assert exc.value.messages == expected


@pytest.mark.parametrize("names,expected", CASES)
def test_update_reports_the_field_being_set(owner_cls, names, expected):
    instance = owner_cls()
    first = names[0]

    with pytest.raises(ValidationError) as exc:
        for name in names:
            setattr(instance, name, _bad(name))

    expected_first = {
        key: value
        for key, value in expected.items()
        if key == first or key.startswith(f"{first}.")
    }
    assert expected_first
    assert type(exc.value.messages) is dict
    assert exc.value.messages == expected_first


def test_missing_key_on_descriptor_error_raises_key_error(owner_cls):
    with pytest.raises(ValidationError) as exc:
        owner_cls(a=Addr(city="x"))

    with pytest.raises(KeyError):
        exc.value.messages["b"]


def test_passing_validators_raise_nothing(owner_cls):
    instance = owner_cls(s="ok", t="ok", w="x", a=Addr(city="ok"), l=[Addr(city="ok")])

    assert instance.s == "ok"
    assert instance.w == "x"
    assert instance.a == Addr(city="ok")


def test_simple_field_code_is_carried(owner_cls):
    with pytest.raises(ValidationError) as exc:
        owner_cls(u="x")

    assert exc.value.messages == {"u": ["has x"]}
    assert exc.value.codes == ["PRT-X"]


def test_simple_field_code_is_carried_on_update(owner_cls):
    instance = owner_cls()

    with pytest.raises(ValidationError) as exc:
        instance.u = "x"

    assert exc.value.codes == ["PRT-X"]


def test_descriptor_field_codes_are_carried_once(owner_cls):
    with pytest.raises(ValidationError) as exc:
        owner_cls(c=Addr(city="x"))

    assert exc.value.messages == {"c": ["has x", "has x again"]}
    assert exc.value.codes == ["PRT-X"]


def test_descriptor_field_code_is_carried_on_update(owner_cls):
    instance = owner_cls()

    with pytest.raises(ValidationError) as exc:
        instance.c = Addr(city="x")

    assert exc.value.codes == ["PRT-X"]


def test_codes_from_simple_and_descriptor_fields_are_merged(owner_cls):
    with pytest.raises(ValidationError) as exc:
        owner_cls(u="x", c=Addr(city="x"))

    assert exc.value.messages == {"u": ["has x"], "c": ["has x", "has x again"]}
    assert exc.value.codes == ["PRT-X"]


def test_create_validates_value_object_given_through_shadow_fields(owner_cls):
    with pytest.raises(ValidationError) as exc:
        owner_cls(s="x", a_city="x")

    assert exc.value.messages == {"s": ["has x"], "a": ["has x"]}


class Ledger(BaseAggregate):
    s = String(validators=[no_x])
    c = ValueObject(Addr, validators=[no_x_coded, no_x_coded_again])


def test_update_through_dao_carries_codes(test_domain):
    test_domain.register(Addr)
    test_domain.register(Ledger)
    test_domain.init(traverse=False)
    instance = Ledger(s="ok")
    repository = test_domain.repository_for(Ledger)
    repository.add(instance)

    with pytest.warns(RemovedInProtean020Warning):
        with pytest.raises(ValidationError) as exc:
            repository._dao.update(instance, s="x", c=Addr(city="x"))

    assert exc.value.messages == {"s": ["has x"], "c": ["has x", "has x again"]}
    assert exc.value.codes == ["PRT-X"]


def test_uncoded_failure_carries_no_code(owner_cls):
    with pytest.raises(ValidationError) as exc:
        owner_cls(s="x", a=Addr(city="x"))

    assert exc.value.codes == []


class Line(BaseEntity):
    sku = String()


class Basket(BaseAggregate):
    label = String(validators=[no_x])
    lines = HasMany(Line)
    a = ValueObject(Addr, validators=[no_x])


def test_create_skips_associations_when_collecting_descriptor_errors(test_domain):
    test_domain.register(Addr)
    test_domain.register(Basket)
    test_domain.register(Line, part_of=Basket)
    test_domain.init(traverse=False)

    with pytest.raises(ValidationError) as exc:
        Basket(label="x", lines=[Line(sku="ok")], a=Addr(city="x"))

    assert exc.value.messages == {"label": ["has x"], "a": ["has x"]}


class Shipment(BaseAggregate):
    label = String(validators=[no_x])
    a = ValueObject(Addr, validators=[no_x])
    dest = ValueObject(Addr, required=True)


@pytest.fixture
def shipment_cls(test_domain):
    test_domain.register(Addr)
    test_domain.register(Shipment)
    test_domain.init(traverse=False)
    return Shipment


def test_create_reports_missing_required_beside_failing_descriptor(shipment_cls):
    with pytest.raises(ValidationError) as exc:
        shipment_cls(label="ok", a=Addr(city="x"))

    assert exc.value.messages == {"a": ["has x"], "dest": ["is required"]}


def test_create_reports_missing_required_beside_failing_simple_field(shipment_cls):
    with pytest.raises(ValidationError) as exc:
        shipment_cls(label="x", a=Addr(city="x"))

    assert exc.value.messages == {
        "label": ["has x"],
        "a": ["has x"],
        "dest": ["is required"],
    }


def test_create_with_required_given_reports_only_failing_descriptor(shipment_cls):
    with pytest.raises(ValidationError) as exc:
        shipment_cls(label="ok", a=Addr(city="x"), dest=Addr(city="Paris"))

    assert exc.value.messages == {"a": ["has x"]}


class Placement(BaseAggregate):
    name = String()


class PlaceIt(BaseCommand):
    s = String(validators=[no_x_coded])


class PlacedIt(BaseEvent):
    s = String(validators=[no_x_coded])


class Tag(BaseValueObject):
    s = String(validators=[no_x_coded])


class Listing(BaseProjection):
    listing_id = Identifier(identifier=True)
    s = String(validators=[no_x_coded])


class FindListing(BaseQuery):
    s = String(validators=[no_x_coded])


@pytest.fixture
def coded_elements(test_domain):
    test_domain.register(Placement)
    test_domain.register(PlaceIt, part_of=Placement)
    test_domain.register(PlacedIt, part_of=Placement)
    test_domain.register(Tag)
    test_domain.register(Listing)
    test_domain.register(FindListing, part_of=Listing)
    test_domain.init(traverse=False)


@pytest.mark.parametrize("element_cls", [PlaceIt, PlacedIt, Tag, FindListing])
def test_other_element_kinds_carry_validator_codes(coded_elements, element_cls):
    with pytest.raises(ValidationError) as exc:
        element_cls(s="x")

    assert exc.value.messages == {"s": ["has x"]}
    assert exc.value.codes == ["PRT-X"]


def test_projection_construction_carries_validator_codes(coded_elements):
    with pytest.raises(ValidationError) as exc:
        Listing(listing_id="1", s="x")

    assert exc.value.messages == {"s": ["has x"]}
    assert exc.value.codes == ["PRT-X"]


def test_projection_assignment_carries_validator_codes(coded_elements):
    listing = Listing(listing_id="1", s="ok")
    with pytest.raises(ValidationError) as exc:
        listing.s = "x"

    assert exc.value.messages == {"s": ["has x"]}
    assert exc.value.codes == ["PRT-X"]


class ShortAddr(BaseValueObject):
    city = String(max_length=3)


class Depot(BaseAggregate):
    label = String(validators=[no_x])
    site = ValueObject(ShortAddr)
    a = ValueObject(Addr, validators=[no_x])


@pytest.fixture
def depot_cls(test_domain):
    test_domain.register(ShortAddr)
    test_domain.register(Addr)
    test_domain.register(Depot)
    test_domain.init(traverse=False)
    return Depot


@pytest.mark.parametrize(
    "kwargs", [{"site_city": "toolong"}, {"site": {"city": "toolong"}}]
)
def test_value_object_own_field_error_keeps_its_own_key(depot_cls, kwargs):
    with pytest.raises(ValidationError) as exc:
        depot_cls(label="x", **kwargs)

    assert exc.value.messages == {
        "label": ["has x"],
        "city": ["String should have at most 3 characters"],
    }


def test_shadow_built_value_object_reported_beside_failing_descriptor(depot_cls):
    with pytest.raises(ValidationError) as exc:
        depot_cls(label="ok", site_city="toolong", a=Addr(city="x"))

    assert exc.value.messages == {
        "city": ["String should have at most 3 characters"],
        "a": ["has x"],
    }
