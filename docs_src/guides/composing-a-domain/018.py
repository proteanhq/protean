from protean import Domain
from protean.fields import Integer, String
from protean.globals import current_domain

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class User:
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()


domain.init(traverse=False)


with domain.domain_context().push():
    # Access an active, connected instance of User Repository
    user_repo = current_domain.repository_for(User)
