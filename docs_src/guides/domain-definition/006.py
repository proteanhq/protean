from protean import Domain
from protean.fields import String

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class UserProfile:
    name = String(max_length=30)


print(UserProfile.meta_.schema_name)
# 'user_profile'
