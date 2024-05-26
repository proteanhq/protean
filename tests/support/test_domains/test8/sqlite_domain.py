"""Dummy Domain file to test domain loading with config
for further testing, like docker file generation
"""

from protean.domain import Domain

domain = Domain(__file__, "SQLite-Domain", load_toml=False)


domain.config["databases"] = {
    "default": {
        "provider": "sqlalchemy",
        "database": "sqlite",
        "database_uri": "sqlite:///:memory:",
    }
}
