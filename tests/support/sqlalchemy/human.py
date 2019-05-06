""" Define entities of the Human Type """
from datetime import datetime

from protean.core import field
from protean.core.entity import Entity
from protean.core.field import association


class SqlHuman(Entity):
    """This is a dummy Dog Entity class"""
    name = field.StringMedium(required=True, unique=True)
    age = field.Integer()
    weight = field.Float()
    is_married = field.Boolean(default=True)
    date_of_birth = field.Date(required=True)
    hobbies = field.List()
    profile = field.Dict()
    address = field.Text()
    created_at = field.DateTime(default=datetime.utcnow)

    class Meta:
        provider = 'sql_another_db'


class SqlRelatedHuman(Entity):
    """This is a dummy Dog Entity class"""
    name = field.StringMedium(required=True, unique=True)
    age = field.Integer()
    weight = field.Float()
    date_of_birth = field.Date(required=True)
    dogs = association.HasMany('SqlRelatedDog', via='owner_id')

    class Meta:
        provider = 'sql_db'
