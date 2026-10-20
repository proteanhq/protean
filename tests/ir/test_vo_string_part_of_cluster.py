"""A value object with a string `part_of` lands in its aggregate's IR cluster."""

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import Dict, Float, String, ValueObject
from protean.ir.builder import IRBuilder
from protean.utils import fqn


class TierPrice(BaseValueObject):
    amount: Float(required=True)


def _assert_in_cluster(ir, vo_cls, aggregate_cls):
    cluster = ir["clusters"][fqn(aggregate_cls)]
    assert fqn(vo_cls) in cluster["value_objects"]
    assert cluster["value_objects"][fqn(vo_cls)]["part_of"] == fqn(aggregate_cls)


def test_unembedded_value_object_is_in_part_of_cluster(test_domain):
    class Product(BaseAggregate):
        name: String()

    test_domain.register(Product)
    test_domain.register(TierPrice, part_of="Product")
    test_domain.init(traverse=False)

    ir = IRBuilder(test_domain).build()

    _assert_in_cluster(ir, TierPrice, Product)


def test_value_object_inside_dict_is_in_part_of_cluster(test_domain):
    class Product(BaseAggregate):
        name: String()
        tiers = Dict(value_type=ValueObject(TierPrice))

    test_domain.register(Product)
    test_domain.register(TierPrice, part_of="Product")
    test_domain.init(traverse=False)

    ir = IRBuilder(test_domain).build()

    _assert_in_cluster(ir, TierPrice, Product)


def test_embedded_value_object_with_string_part_of_keeps_building(test_domain):
    class Product(BaseAggregate):
        name: String()
        price = ValueObject(TierPrice)

    test_domain.register(Product)
    test_domain.register(TierPrice, part_of="Product")
    test_domain.init(traverse=False)

    ir = IRBuilder(test_domain).build()

    _assert_in_cluster(ir, TierPrice, Product)
