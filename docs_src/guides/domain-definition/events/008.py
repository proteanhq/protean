from protean import Domain
from protean.fields import DateTime, Identifier, String

domain = Domain(name="Authentication")


@domain.aggregate
class User:
    name: String(max_length=50)


# --8<-- [start:event]
@domain.event(part_of=User, version=2)
class UserActivated:
    user_id: Identifier(required=True)
    activated_at: DateTime(required=True)


# --8<-- [end:event]
