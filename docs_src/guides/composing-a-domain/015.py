from protean import BaseAggregate, Domain
from protean.fields import Integer, String

domain = Domain(__file__, load_toml=False)


class User(BaseAggregate):
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()

    class Meta:
        stream_name = "account"


domain.register(User)
