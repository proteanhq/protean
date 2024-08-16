from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import Integer, String

domain = Domain(__file__, load_toml=False)


class User(BaseAggregate):
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()


domain.register(User, stream_category="account")
