"""Shared test domain elements for IR builder tests."""

from protean import Domain
from protean.fields import HasMany, ValueObject as VOField

from protean.fields.containers import Dict, List
from protean.fields.simple import (
    Boolean,
    Date,
    DateTime,
    Float,
    Identifier,
    Integer,
    String,
    Text,
)


def build_field_test_domain() -> Domain:
    """Build a domain with diverse field types for field extraction tests."""
    domain = Domain(name="FieldTest", root_path=".")

    @domain.value_object
    class Address:
        street = String(max_length=255, required=True)
        city = String(max_length=100, required=True)
        zip_code = String(max_length=10, required=True)

    @domain.entity(part_of="Product")
    class Variant:
        name = String(max_length=100, required=True)
        sku = String(max_length=50)

    @domain.aggregate
    class Product:
        name = String(max_length=200, required=True, sanitize=True)
        description = Text()
        price = Float(min_value=0.0)
        quantity = Integer(min_value=0)
        is_active = Boolean(default=True)
        created_at = DateTime()
        launch_date = Date()
        sku = Identifier(required=True)
        tags = List(content_type=str)
        metadata_field = Dict()
        shipping_address = VOField(Address)
        variants = HasMany(Variant)
        status = String(max_length=20, choices=["ACTIVE", "INACTIVE", "ARCHIVED"])
        score = Float(default=0.0)

    domain.init(traverse=False)
    return domain
