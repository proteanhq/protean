from protean.utils import IdentityStrategy


DEBUG = True

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = 'abcdefghijklmn'

# Flag indicates that we are testing
TESTING = True

# Database Configuration
DATABASES = {
    'default': {
        'PROVIDER': 'protean.impl.repository.dict_repo.DictProvider'
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

# Messaging Mediums
BROKERS = {
    'default': {
        'PROVIDER': 'protean.impl.broker.memory_broker.MemoryBroker'
    }
}
