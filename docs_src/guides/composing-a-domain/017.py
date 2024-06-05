from protean import Domain

domain = Domain(__file__, load_toml=False)

domain.config["DATABASES"]["default"] = {
    "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
    "DATABASE": "SQLITE",
    "DATABASE_URI": "sqlite:///:memory:",
}

domain.init(traverse=False)
