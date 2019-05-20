""" Define entities of the Dog Type """
# Protean
from protean import Entity
from protean.core.field.basic import String, Integer
from protean.core.field.association import Reference


@Entity
class SqlDog:
    """This is a dummy Dog Entity class"""
    name = String(required=True, max_length=50, unique=True)
    owner = String(required=True, max_length=15)
    age = Integer(default=5)

    class Meta:
        provider = 'sql_db'


@Entity
class SqlRelatedDog:
    """This is a dummy Dog Entity class"""
    name = String(required=True, max_length=50, unique=True)
    owner = Reference('SqlRelatedHuman')
    age = Integer(default=5)

    class Meta:
        provider = 'sql_db'
