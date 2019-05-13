"""Sample Config Module for testing purposes"""
import datetime

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
    },
    'sql_db': {
        'PROVIDER': 'protean.impl.repository.sqlalchemy_repo.SAProvider',
        'DATABASE_URI': 'sqlite:///test.db'
    },
    'sql_another_db': {
        'PROVIDER': 'protean.impl.repository.sqlalchemy_repo.SAProvider',
        'DATABASE_URI': 'sqlite:///another_test.db'
    }
}

# Define the cache config
CACHE = {
    'PROVIDER': 'protean.impl.cache.local_mem.LocalMemCache'
}

# Email Configuration
DEFAULT_FROM_EMAIL = 'johndoe@domain.com'

# JWT Backend related configuration
JWT_ACCESS_TOKEN_EXPIRES = datetime.timedelta(minutes=60)
JWT_ALGORITHM = 'HS256'
JWT_IDENTITY_CLAIM = 'identity'
