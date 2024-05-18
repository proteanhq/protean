from protean import BaseSerializer
from protean.core.aggregate import BaseAggregate
from protean.fields import Dict, Integer, List


class Foo(BaseAggregate):
    bar = List(content_type=Integer)


class Qux(BaseAggregate):
    bars = List(content_type=Dict, default=list)


class FooRepresentation(BaseSerializer):
    bars = List(content_type=Dict)

    class Meta:
        part_of = Qux


def test_that_list_of_dicts_are_serialized_correctly():
    serialized = FooRepresentation().dump(Qux(bars=[{"a": 1, "b": 1}]))
    assert serialized["bars"] == [{"a": 1, "b": 1}]


def test_that_list_fields_are_not_shared():
    foo1 = Foo(bar=[1, 2])
    foo2 = Foo(bar=[3, 4])

    assert foo1.bar == [1, 2]
    assert foo2.bar == [3, 4]

    qux1 = Qux(bars=[{"a": 1}, {"b": 2}])
    qux2 = Qux(bars=[{"c": 3}, {"d": 4}])

    assert qux1.bars == [{"a": 1}, {"b": 2}]
    assert qux2.bars == [{"c": 3}, {"d": 4}]

    qux3 = Qux()
    qux3.bars.append({"a": 1})
    qux3.bars.append({"b": 2})

    qux4 = Qux()
    assert qux4.bars == []
