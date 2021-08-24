from protean.core.field.basic import Identifier, Integer, String
from protean.core.view import BaseView


class Person(BaseView):
    person_id = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)
