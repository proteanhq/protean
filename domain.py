from protean import Domain

domain = Domain("TestApp", root_path=".")

domain.config.update({
    "databases": {
        "default": {"provider": "postgresql"}
    },
    "caches": {
        "default": {"provider": "redis"}
    }
})