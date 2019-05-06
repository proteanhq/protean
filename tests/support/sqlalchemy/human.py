""" Define entities of the Human Type """
# Standard Library Imports
from datetime import datetime

# Protean
from protean import Entity
from protean.core import field
from protean.core.field import association


@Entity
class SqlHuman:
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


@Entity
class SqlRelatedHuman:
    """This is a dummy Dog Entity class"""
    name = field.StringMedium(required=True, unique=True)
    age = field.Integer()
    weight = field.Float()
    date_of_birth = field.Date(required=True)
    dogs = association.HasMany('SqlRelatedDog', via='owner_id')

    class Meta:
        provider = 'sql_db'
