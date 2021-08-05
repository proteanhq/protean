from protean.utils import Database, IdentityStrategy, IdentityType

DEBUG = True
TESTING = True
ENV = "development"

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = "tvTpk3PAfkGr5x9!2sFU%XpW7bR8cwKA"

# Database Configuration
DATABASES = {
    "default": {"PROVIDER": "protean.adapters.MemoryProvider"},
    "sqlite": {
        "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
        "DATABASE": Database.SQLITE.value,
        "DATABASE_URI": "sqlite:///test.db",
    },
}

# Identity strategy to use when persisting Entities/Aggregates.
#
# Options:
#
#   * IdentityStrategy.UUID: Default option, and preferred. Identity is a UUID and generated during `build` time.
#       Persisted along with other details into the data store.
#   * IdentityStrategy.DATABASE: Let the database generate unique identity during persistence
#   * IdentityStrategy.FUNCTION: Special function that returns a unique identifier
IDENTITY_STRATEGY = IdentityStrategy.UUID.value

# Data type of Auto-Generated Identity Values
#
# Options:
#
#   * INTEGER
#   * STRING (Default)
IDENTITY_TYPE = IdentityType.STRING.value

# Messaging Mediums
BROKERS = {
    "default": {
        "PROVIDER": "protean.adapters.broker.celery.CeleryBroker",
        "URI": "redis://127.0.0.1:6379/2",
        "IS_ASYNC": True,
    },
}

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {"format": "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"},
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
    },
    "loggers": {"protean": {"handlers": ["console"], "level": "DEBUG"}},
}
