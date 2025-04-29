from protean import Domain

domain = Domain("TestApp")
domain.root_path = "."

domain.config.update({
    "databases": {
        "default": {"provider": "postgresql"}
    },
    "caches": {
        "default": {"provider": "redis"}
    }
})