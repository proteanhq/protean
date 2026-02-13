from protean.core.projection import _LegacyBaseProjection as BaseProjection
from protean.fields import Identifier, Integer, String


class Person(BaseProjection):
    person_id = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)
