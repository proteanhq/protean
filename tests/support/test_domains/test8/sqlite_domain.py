from protean.domain import Domain

domain = Domain(__file__, "SQLite-Domain")


domain.config["DATABASES"] = {
    "default": {
        "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
        "DATABASE": "sqlite",
        "DATABASE_URI": "sqlite:///:memory:",
    }
}
