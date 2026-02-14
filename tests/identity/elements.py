from protean.core.aggregate import BaseAggregate


class Person(BaseAggregate):
    first_name: str
    last_name: str
    age: int = 21
