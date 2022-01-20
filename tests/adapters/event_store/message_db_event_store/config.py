# cSpell: disable

from protean.utils import IdentityStrategy, IdentityType

####################
# CORE             #
####################

DEBUG = True
TESTING = True
ENV = "development"

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = "nU5JSWCP#4c#Annek2mx9V&g5uWUJfh@"

IDENTITY_STRATEGY = IdentityStrategy.UUID.value
IDENTITY_TYPE = IdentityType.UUID.value

# Define the databases
EVENT_STORE = {
    "PROVIDER": "protean.adapters.event_store.message_db.MessageDBStore",
    "DATABASE_URI": "postgresql://message_store@localhost:5433/message_store",
}
