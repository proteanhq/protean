from datetime import datetime

from protean import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields.basic import DateTime, String
from protean.fields.embedded import ValueObject


class SimpleVO(BaseValueObject):
    foo = String()
    bar = String()


class VOWithDateTime(BaseValueObject):
    foo = String()
    now = DateTime()


class SimpleVOEntity(BaseAggregate):
    vo = ValueObject(SimpleVO)


class EntityWithDateTimeVO(BaseAggregate):
    vo = ValueObject(VOWithDateTime)


class TestAsDict:
    def test_empty_simple_vo(self):
        simple = SimpleVOEntity(id=12)
        assert simple.to_dict() == {"id": 12}

    def test_simple_vo_dict(self):
        vo = SimpleVO(foo="foo", bar="bar")
        assert vo.to_dict() == {"foo": "foo", "bar": "bar"}

    def test_embedded_simple_vo(self):
        vo = SimpleVO(foo="foo", bar="bar")
        simple = SimpleVOEntity(id=12, vo=vo)
        assert simple.to_dict() == {"id": 12, "vo": {"foo": "foo", "bar": "bar"}}

    def test_datetime_vo_dict(self):
        now = datetime.utcnow()
        vo = VOWithDateTime(foo="foo", now=now)
        assert vo.to_dict() == {"foo": "foo", "now": str(now)}

    def test_embedded_datetime_vo(self):
        now = datetime.utcnow()
        vo = VOWithDateTime(foo="foo", now=now)
        simple = EntityWithDateTimeVO(id=12, vo=vo)
        assert simple.to_dict() == {"id": 12, "vo": {"foo": "foo", "now": str(now)}}
