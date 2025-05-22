from protean import Domain

domain = Domain("TestApp")
domain.root_path = "."

domain.config.update({
    "databases": {
        "default": {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres"
        }
    },
    "caches": {
        "default": {
            "provider": "redis",
            "URI": "redis://localhost:6379/0"
        }
    }
})