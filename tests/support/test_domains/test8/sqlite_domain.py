"""Dummy Domain file to test domain loading with config
for further testing, like docker file generation
"""

from protean.domain import Domain

domain = Domain(__file__, "SQLite-Domain", load_toml=False)


domain.config["DATABASES"] = {
    "default": {
        "PROVIDER": "sqlalchemy",
        "DATABASE": "sqlite",
        "DATABASE_URI": "sqlite:///:memory:",
    }
}
