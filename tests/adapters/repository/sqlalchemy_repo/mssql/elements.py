from protean.core.aggregate import BaseAggregate


class MssqlTestEntity(BaseAggregate):
    name: str | None = None
    description: str | None = None
    age: int | None = None
