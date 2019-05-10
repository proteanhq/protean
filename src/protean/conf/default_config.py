"""
Default settings. Override these with settings in the module pointed to
by the PROTEAN_CONFIG environment variable.
"""

# Protean
from protean.utils import IdentityStrategy

####################
# CORE             #
####################

DEBUG = False

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = 'wR5yJVF!PVA3&bBaFK%e3#MQna%DJfyT'

##########
# DOMAIN #
##########

# Identity strategy to use when persisting Entities/Aggregates.
#
# Options:
#
#   * IdentityStrategy.UUID: Default option, and preferred. Identity is a UUID and generated during `build` time.
#       Persisted along with other details into the data store.
#   * IdentityStrategy.DATABASE: Let the database generate unique identity during persistence
#   * IdentityStrategy.FUNCTION: Special function that returns a unique identifier
IDENTITY_STRATEGY = IdentityStrategy.UUID

###############
#  REPOSITORY #
###############

# Repository connection information
DATABASES = {}

# Default no. of records to fetch per query
RESULTS_LIMIT = 10

####################
# GENERIC CACHE    #
####################
# Cache connection information
CACHE = {}

####################
# GENERIC EMAIL    #
####################

EMAIL_BACKEND = 'protean.impl.email.local_mem.EmailBackend'
DEFAULT_FROM_EMAIL = None

####################
# Logging          #
####################

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            'format': '%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
        }
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'console',
        }
    },
    'loggers': {
        'protean': {
            'handlers': ['console'],
            'level': 'INFO',
        }
    }
}

####################
# APIs             #
####################

# Default content type of the input data if none provided
DEFAULT_CONTENT_TYPE = 'application/json'

# Custom exception handler for the app
EXCEPTION_HANDLER = None

# Default output renderer for the app
DEFAULT_RENDERER = 'protean.impl.api.flask.renderers.render_json'
