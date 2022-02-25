from protean import BaseSerializer
from protean.core.aggregate import BaseAggregate
from protean.fields import Dict, List


class Qux(BaseAggregate):
    bars = List(content_type=Dict)


class FooRepresentation(BaseSerializer):
    bars = List(content_type=Dict)

    class Meta:
        aggregate_cls = Qux


def test_that_list_of_dicts_are_serialized_correctly():
    serialized = FooRepresentation().dump(Qux(bars=[{"a": 1, "b": 1}]))
    assert serialized["bars"] == [{"a": 1, "b": 1}]
