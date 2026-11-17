from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Integer, String


class MssqlTestEntity(BaseAggregate):
    name: String(max_length=50)
    description: String(max_length=200)
    age: Integer()


class MssqlTimestampedEntity(BaseAggregate):
    label: String(max_length=50)
    occurred_at: DateTime()
