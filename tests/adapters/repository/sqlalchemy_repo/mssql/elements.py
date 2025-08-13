from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class MssqlTestEntity(BaseAggregate):
    name = String(max_length=50)
    description = String(max_length=200)
    age = Integer()
