# Protean
from protean.utils import Database, IdentityStrategy, IdentityType

####################
# CORE             #
####################

DEBUG = True

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = 'nU5JSWCP#4c#Annek2mx9V&g5uWUJfh@'

# Flag indicates that we are testing
TESTING = True

IDENTITY_STRATEGY = IdentityStrategy.UUID
IDENTITY_TYPE = IdentityType.UUID

# Define the databases
DATABASES = {
    'default': {
        'PROVIDER': 'protean.impl.repository.elasticsearch_repo.ESProvider',
        'DATABASE': Database.ELASTICSEARCH.value,
        'DATABASE_URI': {'hosts': ['localhost']}
    }
}
