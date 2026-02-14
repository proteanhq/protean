from protean import Domain

domain = Domain()


@domain.aggregate
class Building:
    permit: list[str]
