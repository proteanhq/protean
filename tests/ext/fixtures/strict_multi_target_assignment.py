"""Fixture: a chained or tuple assignment in a class body declares no field.

An assignment declares a field only as ``name = Factory(...)``, with one plain
name on the left. The plugin skips ``left = right = String()`` and
``first, second = String(), String()``, so ``__init__`` takes none of their
names as keywords. The same holds for ``HasMany``: neither form gets
``add_<name>`` or ``remove_<name>``.
"""

from protean.domain import Domain
from protean.fields import HasMany, String

domain = Domain(name="Strict")


@domain.entity(part_of="Order")
class LineItem:
    sku: String(required=True)


@domain.aggregate
class Order:
    left = right = String()
    first, second = String(), String()
    lines_a = lines_b = HasMany(LineItem)
    head, tail = HasMany(LineItem)


Order(left="x")  # E: call-arg
Order(first="x")  # E: call-arg
order = Order()
order.add_lines_a(LineItem(sku="a"))  # E: attr-defined
order.add_head(LineItem(sku="a"))  # E: attr-defined
