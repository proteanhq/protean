# --8<-- [start:full]
# --8<-- [start:setup]
import os

from protean import Domain
from protean.fields import Float, Identifier

domain = Domain(name="Orders")
domain.config["caches"]["default"] = {
    "provider": "redis",
    "URI": os.environ.get("REDIS_URL", "redis://localhost:6379/2"),
    "TTL": 300,
}


@domain.projection(cache="default")
class OrderSummary:
    order_id: Identifier(identifier=True)
    total: Float()


domain.init(traverse=False)
# --8<-- [end:setup]

# --8<-- [start:usage]
with domain.domain_context():
    # Get the cache that holds the projection
    cache = domain.cache_for(OrderSummary)

    # Check connectivity
    reachable = cache.ping()  # True if Redis is reachable

    # Store a projection; its key is "order_summary:::ord-123"
    cache.add(OrderSummary(order_id="ord-123", total=42.5))

    # Retrieve a cached projection
    entry = cache.get("order_summary:::ord-123")

    # Count cached entries
    count = cache.count("order_summary:::*")

    # Set a custom TTL on a specific key
    cache.set_ttl("order_summary:::ord-123", ttl=600)  # 10 minutes
    remaining = cache.get_ttl("order_summary:::ord-123")

    # Remove all entries
    cache.flush_all()
# --8<-- [end:usage]
# --8<-- [end:full]
