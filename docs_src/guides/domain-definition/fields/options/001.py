from protean import Domain

domain = Domain()


@domain.aggregate
class Person:
    name: str
