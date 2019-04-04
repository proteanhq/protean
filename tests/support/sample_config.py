"""Sample Config Module for testing purposes"""
DEBUG = False

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

# Define the cache config
CACHE = {
    'PROVIDER': 'protean.impl.cache.local_mem.LocalMemCache'
}

# Email Configuration
DEFAULT_FROM_EMAIL = 'johndoe@domain.com'
