from tests.support.domains.test13.publishing13 import domain


@domain.aggregate
class User:
    first_name: str | None = None
    last_name: str | None = None
