from protean import Domain

domain = Domain(__file__, load_toml=False)

# Non-existent database
domain.config["databases"]["default"] = {
    "provider": "postgresql",
    "database_uri": "postgresql://postgres:postgres@localhost:5444/foobar",  # (1)
}

domain.init(traverse=False)

# Output
#
# protean.exceptions.ConfigurationError:
# Could not connect to database at postgresql://postgres:postgres@localhost:5444/foobar
