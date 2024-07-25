from protean.core.aggregate import BaseAggregate
from protean.core.serializer import BaseSerializer
from protean.fields import Integer, String


class User(BaseAggregate):
    name = String(required=True)
    age = Integer(required=True)


class UserSchema(BaseSerializer):
    name = String(required=True)
    age = Integer(required=True)

    class Meta:
        part_of = User
