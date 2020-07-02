# cSpell: disable

# Protean
from protean.utils import Database, IdentityStrategy, IdentityType

####################
# CORE             #
####################

DEBUG = True
TESTING = True
ENV = "development"


# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = "nU5JSWCP#4c#Annek2mx9V&g5uWUJfh@"

IDENTITY_STRATEGY = IdentityStrategy.UUID
IDENTITY_TYPE = IdentityType.UUID

# Define the databases
DATABASES = {
    "default": {
        "PROVIDER": "protean.impl.repository.sqlalchemy_repo.SAProvider",
        "DATABASE": Database.POSTGRESQL.value,
        "DATABASE_URI": "postgresql://postgres:@localhost:5432/protean_test",
    },
}
