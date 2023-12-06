import os

from protean.utils import (
    CommandProcessing,
    EventProcessing,
    IdentityStrategy,
    IdentityType,
)


class Config:
    DEBUG = True

    # A secret key for this particular Protean installation. Used in secret-key
    # hashing algorithms.
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "secret-key-that-is-not-so-secret",
    )

    # Flag indicates that we are testing
    TESTING = False

    # Database Configuration
    DATABASES = {
        "default": {"PROVIDER": "protean.adapters.repository.memory.MemoryProvider"},
        "postgresql": {
            "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
            "DATABASE_URI": os.getenv(
                "DATABASE_URL",
                "postgresql://postgres:postgres@localhost:5432/postgres",
            ),
            "SCHEMA": os.getenv("POSTGRES_SCHEMA", "public"),
        },
        "sqlite": {
            "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
            "DATABASE_URI": "sqlite:///test.db",
        },
        "elasticsearch": {
            "PROVIDER": "protean.adapters.repository.elasticsearch.ESProvider",
            "DATABASE_URI": {"hosts": os.getenv("ES_URI", "localhost").split(",")},
            "USE_SSL": os.environ.get("ES_USE_SSL", "false").lower() == "true",
            "VERIFY_CERTS": (
                os.environ.get("ES_VERIFY_CERTS", "false").lower() == "true"
            ),  # default false
            "NAMESPACE_PREFIX": os.environ.get("ES_NAMESPACE_PREFIX", "dev"),
            "SETTINGS": {},
        },
    }

    EVENT_STORE = {
        "PROVIDER": "protean.adapters.event_store.memory.MemoryEventStore",
    }

    # MessageDB EventStore Configuration
    # EVENT_STORE = {
    #     "PROVIDER": "protean.adapters.event_store.message_db.MessageDBStore",
    #     "DATABASE_URI": "postgresql://message_store@localhost:5433/message_store",
    # }

    BROKERS = {
        "default": {"PROVIDER": "protean.adapters.broker.memory_broker.MemoryBroker"},
        "redis": {
            "PROVIDER": "protean.adapters.broker.redis.RedisBroker",
            "URI": f'{os.getenv("CACHE_URL","redis://127.0.0.1:6379")}/0',
            "IS_ASYNC": True,
        },
        "celery": {
            "PROVIDER": "protean.adapters.broker.celery.CeleryBroker",
            "URI": os.environ.get("BROKER_URI") or "redis://127.0.0.1:6379/2",
            "IS_ASYNC": (
                os.environ.get("BROKER_IS_ASYNC", "True") in ["True", "true"]
            ),  # True by default
        },
    }

    CACHES = {
        "default": {
            "PROVIDER": "protean.adapters.cache.memory.MemoryCache",
            "TTL": 300,
        },
        "redis": {
            "PROVIDER": "protean.adapters.cache.redis.RedisCache",
            "URI": f'{os.getenv("CACHE_URL","redis://127.0.0.1:6379")}/2',
            "TTL": 300,
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
    IDENTITY_TYPE = IdentityType.UUID.value

    EVENT_PROCESSING = EventProcessing.ASYNC.value
    COMMAND_PROCESSING = CommandProcessing.SYNC.value

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "format": "%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "level": "INFO",
                "class": "logging.StreamHandler",
                "formatter": "console",
            },
        },
        "loggers": {
            "protean": {"handlers": ["console"], "level": "INFO"},
        },
    }


class TestingConfig(Config):
    TESTING = True


class DevelopmentConfig(Config):
    pass


class ProductionConfig(Config):
    DEBUG = False
