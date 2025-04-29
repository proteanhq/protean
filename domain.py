from protean import Domain

domain = Domain("TestApp")

domain.config.update({
    "databases": {
        "default": {"provider": "postgresql"}
    },
    "caches": {
        "default": {"provider": "redis"}
    }
})