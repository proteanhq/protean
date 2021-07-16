from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Integer, String
from protean.core.serializer import BaseSerializer


class User(BaseAggregate):
    name = String(required=True)
    age = Integer(required=True)


class UserSchema(BaseSerializer):
    name = String(required=True)
    age = Integer(required=True)

    class Meta:
        aggregate_cls = User
