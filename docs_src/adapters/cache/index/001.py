# --8<-- [start:full]
import math

from protean import Domain
from protean.fields import Identifier, String

domain = Domain(name="CacheTTL")


@domain.projection(cache="default")
class Dashboard:
    user_id: Identifier(identifier=True)
    summary: String()


domain.init(traverse=False)


def describe_ttl(cache, key):
    remaining = cache.get_ttl(key)
    if remaining is None:
        return "missing"  # no such key
    elif remaining == math.inf:
        return "never expires"
    else:
        return f"{math.ceil(remaining)}s left"  # whole seconds remaining


with domain.domain_context():
    cache = domain.cache_for(Dashboard)
    cache.add(Dashboard(user_id="u-1", summary="3 open orders"), ttl=60)

    present = describe_ttl(cache, "dashboard:::u-1")
    missing = describe_ttl(cache, "dashboard:::u-2")
# --8<-- [end:full]
