# --8<-- [start:full]
from protean import Domain
from protean.fields import Boolean, Identifier, String
from protean.utils import IdentityType

domain = Domain()

# Customize the identity type
domain.config["identity_type"] = IdentityType.INTEGER.value


@domain.aggregate
class User:
    user_id: Identifier(identifier=True)
    name: String(required=True)
    subscribed: Boolean(default=False)


# --8<-- [end:full]
