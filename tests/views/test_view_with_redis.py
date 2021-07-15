from protean.core.field.basic import Integer, String
from protean.core.view import BaseView


class Person(BaseView):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)
