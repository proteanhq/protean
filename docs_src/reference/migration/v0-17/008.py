from protean import Domain
from protean.fields import Identifier, String

domain = Domain(name="Profiles")


@domain.projection(cache="default")
class UserProfile:
    user_id: Identifier(identifier=True)
    name: String(max_length=50)


# --8<-- [start:get_ttl]
def seconds_left(cache, key):
    # Correct on both Redis and the memory cache
    return cache.get_ttl(key)


# --8<-- [end:get_ttl]
