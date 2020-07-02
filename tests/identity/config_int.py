# Protean
from protean.utils import Database, IdentityStrategy, IdentityType

DEBUG = True
TESTING = True
ENV = "development"

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = "j2t#8U!vy877Rn2W6gQQyz%HmXN3@egV"

# Database Configuration
DATABASES = {
    "default": {
        "PROVIDER": "protean.impl.repository.sqlalchemy_repo.SAProvider",
        "DATABASE": Database.SQLITE.value,
        "DATABASE_URI": "sqlite:///test.db",
    },
}

IDENTITY_STRATEGY = IdentityStrategy.UUID
IDENTITY_TYPE = IdentityType.INTEGER

# Messaging Mediums
BROKERS = {
    "default": {"PROVIDER": "protean.impl.broker.memory_broker.MemoryBroker"},
}
