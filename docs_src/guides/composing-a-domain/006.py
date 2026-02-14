from protean import Domain

domain = Domain()


@domain.aggregate(is_event_sourced=True)
class Person:
    name: str | None = None
    age: int | None = None
