####################
# CORE             #
####################

DEBUG = True

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = 'nU5JSWCP#4c#Annek2mx9V&g5uWUJfh@'

# Flag indicates that we are testing
TESTING = True

# Define the databases
DATABASES = {
    'default': {
        'PROVIDER': 'protean.impl.repository.sqlalchemy_repo.SAProvider',
        'DATABASE_URI': 'sqlite:///test.db'
    }
}
