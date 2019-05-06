""" Define entities of the Dog Type """
from protean.core import field
from protean.core.entity import Entity
from protean import DomainElement


@DomainElement
class SqlDog(Entity):
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, max_length=50, unique=True)
    owner = field.String(required=True, max_length=15)
    age = field.Integer(default=5)

    class Meta:
        provider = 'sql_db'


@DomainElement
class SqlRelatedDog(Entity):
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, max_length=50, unique=True)
    owner = field.Reference('SqlRelatedHuman')
    age = field.Integer(default=5)

    class Meta:
        provider = 'sql_db'
