# Standard Library Imports
from datetime import datetime

# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import DateTime, Integer, String
from protean.core.repository.base import BaseRepository


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)
    created_at = DateTime(default=datetime.now())


class PersonRepository(BaseRepository):
    pass


class Alien(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class User(BaseAggregate):
    email = String(max_length=255, required=True, unique=True)
    password = String(max_length=3026)
