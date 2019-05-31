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
