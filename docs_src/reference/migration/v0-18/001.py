import logging

# --8<-- [start:ttl_imports]
import math

# --8<-- [end:ttl_imports]
# isort: split

from protean import Domain
from protean.fields import Identifier, String

log = logging.getLogger(__name__)

domain = Domain(name="Profiles")


@domain.projection(cache="default")
class UserProfile:
    user_id: Identifier(identifier=True)
    name: String(max_length=50)


# --8<-- [start:remove_by_key]
def remove_cached(cache, key):
    # Ask before removing, and it works on either adapter
    if cache.get(key) is None:
        log.info("nothing cached for %s", key)
    cache.remove_by_key(key)


# --8<-- [end:remove_by_key]


# --8<-- [start:get_ttl]
def describe_ttl(cache, key):
    # One shape on both adapters
    ttl = cache.get_ttl(key)
    if ttl is None:
        return "no such key"
    elif ttl == math.inf:
        return "never expires"
    else:
        return f"{ttl:.0f} seconds remaining"


# --8<-- [end:get_ttl]


# --8<-- [start:glob]
def all_user_profiles(cache):
    # A glob on every adapter, through the private `_get_all`
    return cache._get_all("user_profile:::*")


# --8<-- [end:glob]


# --8<-- [start:get_all]
def process_all(cache, pattern, process):
    # A bounded read of the whole match set (small stores, tests)
    for entry in cache._get_all(pattern):
        process(entry)


# --8<-- [end:get_all]
