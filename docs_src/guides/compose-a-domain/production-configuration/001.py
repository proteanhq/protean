from protean import Domain

# The page's domain.toml points "analytics" at Elasticsearch. The memory
# provider stands in for it here so the example runs without a server.
domain = Domain(
    name="Catalog",
    config={
        "databases": {
            "default": {"provider": "memory"},
            "analytics": {"provider": "memory"},
        }
    },
)


# --8<-- [start:aggregate]
@domain.aggregate(provider="analytics")
class ProductSearch: ...


# --8<-- [end:aggregate]
