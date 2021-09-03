from protean import BaseAggregate, BaseSerializer
from protean.fields import Integer, String


class User(BaseAggregate):
    name = String(required=True)
    age = Integer(required=True)


class UserSchema(BaseSerializer):
    name = String(required=True)
    age = Integer(required=True)

    class Meta:
        aggregate_cls = User
