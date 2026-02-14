from protean import Domain

domain = Domain()


@domain.aggregate
class User:
    name: str
    subscribed: bool = False
