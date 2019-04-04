"""
Default settings. Override these with settings in the module pointed to
by the PROTEAN_CONFIG environment variable.
"""

####################
# CORE             #
####################

DEBUG = False

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = 'wR5yJVF!PVA3&bBaFK%e3#MQna%DJfyT'

####################
# GENERIC REPOSITORY #
####################

# Repository connection information
DATABASES = {}

# Default no. of records to fetch per query
PER_PAGE = 10

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
