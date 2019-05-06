""" Define entities of the Dog Type """
# Protean
from protean import Entity
from protean.core import field


@Entity
class SqlDog:
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, max_length=50, unique=True)
    owner = field.String(required=True, max_length=15)
    age = field.Integer(default=5)

    class Meta:
        provider = 'sql_db'


@Entity
class SqlRelatedDog:
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, max_length=50, unique=True)
    owner = field.Reference('SqlRelatedHuman')
    age = field.Integer(default=5)

    class Meta:
        provider = 'sql_db'
