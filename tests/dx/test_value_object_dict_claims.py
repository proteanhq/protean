"""How the value-object skill describes building a nested value object.

A ``ValueObject`` field takes either a value object instance or a plain dict
of the inner value object's fields, at any depth. A dict is validated like
the constructor call it stands for, so a wrong or missing key raises
``ValidationError``. The skill and its nested-value-objects reference must
say so. The behavior tests pin that to the field, so a change that stops
accepting dicts fails here and forces the skill to change with it.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from protean import Domain, dx
from protean.dx.pack import REFERENCES_DIR as REFERENCES_DIRNAME
from protean.exceptions import ValidationError
from protean.fields import Float, String, ValueObject

SKILL_DIR = Path(str(dx.pack_files())) / dx.SKILLS_DIR / "value-object"
SKILL_MD = SKILL_DIR / "SKILL.md"
NESTED = SKILL_DIR / REFERENCES_DIRNAME / "nested-value-objects.md"

DICT_CLAIM = "also takes a plain dict of the inner value object's fields, at any depth"


@pytest.fixture
def nested() -> SimpleNamespace:
    domain = Domain(name="ValueObjectDicts")

    @domain.value_object
    class Coordinates:
        latitude = Float(required=True)
        longitude = Float(required=True)

    @domain.value_object
    class Address:
        street = String(required=True)
        coordinates = ValueObject(Coordinates)

    @domain.aggregate
    class Store:
        name = String(required=True)
        address = ValueObject(Address)

    domain.init(traverse=False)
    return SimpleNamespace(domain=domain, Address=Address, Store=Store)


@pytest.mark.no_test_domain
@pytest.mark.parametrize("path", [SKILL_MD, NESTED], ids=lambda p: p.name)
def test_file_says_a_value_object_field_takes_a_dict(path: Path) -> None:
    assert DICT_CLAIM in " ".join(path.read_text().split()), path


@pytest.mark.no_test_domain
def test_a_value_object_builds_its_nested_field_from_a_dict(
    nested: SimpleNamespace,
) -> None:
    address = nested.Address(
        street="1 Main", coordinates={"latitude": 1.0, "longitude": 2.0}
    )

    assert type(address.coordinates).__name__ == "Coordinates"
    assert address.coordinates.latitude == 1.0


@pytest.mark.no_test_domain
def test_an_aggregate_builds_value_objects_from_dicts_two_levels_deep(
    nested: SimpleNamespace,
) -> None:
    with nested.domain.domain_context():
        store = nested.Store(
            name="Corner",
            address={
                "street": "1 Main",
                "coordinates": {"latitude": 3.0, "longitude": 4.0},
            },
        )

    assert type(store.address).__name__ == "Address"
    assert type(store.address.coordinates).__name__ == "Coordinates"


@pytest.mark.no_test_domain
def test_a_dict_with_a_wrong_key_raises_validation_error(
    nested: SimpleNamespace,
) -> None:
    with pytest.raises(ValidationError) as exc:
        nested.Address(street="1 Main", coordinates={"lat": 1.0})

    assert "latitude" in exc.value.messages
