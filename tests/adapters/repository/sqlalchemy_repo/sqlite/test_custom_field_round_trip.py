"""A ``Custom`` field against a real database.

The in-memory store keeps whatever Python object it is handed, so it cannot show
whether a custom value reaches the adapter in a form a driver accepts. SQLAlchemy
maps a type it does not know to a string column, so an unserialized instance is
rejected when the driver binds it. These tests run the save, reload and
uniqueness paths against SQLite.
"""

import pytest
from pydantic import PlainSerializer, PlainValidator

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Custom, String, ValueObject


class Color:
    """An RGB color stored as a ``#RRGGBB`` hex string."""

    __slots__ = ("hex",)

    def __init__(self, value: str) -> None:
        self.hex = str(value).upper()

    def to_dict(self) -> str:
        return self.hex

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Color) and other.hex == self.hex

    def __repr__(self) -> str:
        return f"Color({self.hex!r})"


def parse_color(value: object) -> Color:
    if isinstance(value, Color):
        return value
    return Color(value)  # type: ignore[arg-type]


class Brand(BaseAggregate):
    name = String(max_length=50, required=True)
    color = Custom(
        Color,
        validators=[PlainValidator(parse_color)],
        serializers=[PlainSerializer(lambda c: c.hex, return_type=str)],
        required=True,
        unique=True,
    )


@pytest.fixture
def brand_repository(test_domain):
    test_domain.register(Brand)
    test_domain.init(traverse=False)

    provider = test_domain.providers["default"]
    test_domain.repository_for(Brand)._dao
    provider._metadata.create_all(provider._engine)

    return test_domain.repository_for(Brand)


@pytest.mark.sqlite
class TestCustomFieldAgainstSqlite:
    def test_custom_value_saves_and_reloads(self, brand_repository):
        brand = Brand(name="acme", color="#ff0000")
        brand_repository.add(brand)

        reloaded = brand_repository.get(brand.id)
        assert reloaded.color == Color("#FF0000")

    def test_stored_column_holds_the_serialized_value(
        self, brand_repository, test_domain
    ):
        brand_repository.add(Brand(name="acme", color="#ff0000"))

        provider = test_domain.providers["default"]
        rows = provider.raw("SELECT color FROM brand")
        assert [row[0] for row in rows] == ["#FF0000"]

    def test_duplicate_custom_value_is_rejected(self, brand_repository):
        brand_repository.add(Brand(name="acme", color="#ff0000"))

        with pytest.raises(ValidationError):
            brand_repository.add(Brand(name="other", color="#FF0000"))

    def test_query_by_a_custom_instance_finds_the_record(self, brand_repository):
        brand = Brand(name="acme", color="#ff0000")
        brand_repository.add(brand)

        dao = brand_repository._dao
        assert dao.find_by(color=Color("#FF0000")).id == brand.id
        assert dao.find_by(color="#FF0000").id == brand.id


class Palette(BaseValueObject):
    primary = Custom(
        Color,
        validators=[PlainValidator(parse_color)],
        serializers=[PlainSerializer(lambda c: c.hex, return_type=str)],
        required=True,
    )


class Product(BaseAggregate):
    title = String(max_length=50, required=True)
    palette = ValueObject(Palette)


@pytest.fixture
def product_repository(test_domain):
    test_domain.register(Palette)
    test_domain.register(Product)
    test_domain.init(traverse=False)

    provider = test_domain.providers["default"]
    test_domain.repository_for(Product)._dao
    provider._metadata.create_all(provider._engine)

    return test_domain.repository_for(Product)


@pytest.mark.sqlite
class TestCustomFieldInsideValueObjectAgainstSqlite:
    """An embedded value object is flattened into shadow columns."""

    def test_custom_value_in_a_value_object_round_trips(
        self, product_repository, test_domain
    ):
        product = Product(title="lamp", palette=Palette(primary="#00ff00"))
        product_repository.add(product)

        rows = test_domain.providers["default"].raw(
            "SELECT palette_primary FROM product"
        )
        assert [row[0] for row in rows] == ["#00FF00"]

        assert product_repository.get(product.id).palette.primary == Color("#00FF00")
