from protean import Domain

domain = Domain()

domain.config["databases"]["default"] = {
    "provider": "sqlite",
    "database_uri": "sqlite:///test.db",
}

domain.init(traverse=False)
