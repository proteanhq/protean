# Protean
from protean.utils import Database, IdentityStrategy, IdentityType

DEBUG = True
TESTING = True
ENV = 'development'

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = 'tvTpk3PAfkGr5x9!2sFU%XpW7bR8cwKA'

# Database Configuration
DATABASES = {
    'default': {
        'PROVIDER': 'protean.impl.repository.dict_repo.DictProvider'
    },
    'sqlite': {
        'PROVIDER': 'protean.impl.repository.sqlalchemy_repo.SAProvider',
        'DATABASE': Database.SQLITE.value,
        'DATABASE_URI': 'sqlite:///test.db'
    }
}

# Identity strategy to use when persisting Entities/Aggregates.
#
# Options:
#
#   * IdentityStrategy.UUID: Default option, and preferred. Identity is a UUID and generated during `build` time.
#       Persisted along with other details into the data store.
#   * IdentityStrategy.DATABASE: Let the database generate unique identity during persistence
#   * IdentityStrategy.FUNCTION: Special function that returns a unique identifier
IDENTITY_STRATEGY = IdentityStrategy.UUID

# Data type of Auto-Generated Identity Values
#
# Options:
#
#   * INTEGER
#   * STRING (Default)
IDENTITY_TYPE = IdentityType.STRING

# Messaging Mediums
BROKERS = {
    'default': {
        'PROVIDER': 'protean.impl.broker.memory_broker.MemoryBroker'
    }
}

EMAIL_PROVIDERS = {
    'default': {
        "PROVIDER": 'protean.impl.email.dummy.DummyEmailProvider',
        "DEFAULT_FROM_EMAIL": 'admin@team8solutions.com'
    }
}
