""" Define entities of the Human Type """
# Standard Library Imports
from datetime import datetime

# Protean
from protean import Entity
from protean.core.field.basic import Integer, Float, Boolean, Date, List, Dict, Text, DateTime
from protean.core.field.ext import StringMedium
from protean.core.field.association import HasMany


@Entity
class SqlHuman:
    """This is a dummy Dog Entity class"""
    name = StringMedium(required=True, unique=True)
    age = Integer()
    weight = Float()
    is_married = Boolean(default=True)
    date_of_birth = Date(required=True)
    hobbies = List()
    profile = Dict()
    address = Text()
    created_at = DateTime(default=datetime.utcnow)

    class Meta:
        provider = 'sql_another_db'


@Entity
class SqlRelatedHuman:
    """This is a dummy Dog Entity class"""
    name = StringMedium(required=True, unique=True)
    age = Integer()
    weight = Float()
    date_of_birth = Date(required=True)
    dogs = HasMany('SqlRelatedDog', via='owner_id')

    class Meta:
        provider = 'sql_db'
