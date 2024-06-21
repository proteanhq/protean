from protean import Domain
from protean.fields import Integer, String

domain = Domain(__file__, load_toml=False)


@domain.aggregate(stream_name="account")
class User:
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()
