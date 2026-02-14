from protean import Domain
from protean.fields import Boolean, Identifier, String
from protean.utils import IdentityType

domain = Domain()

# Customize Identity Strategy and Type and activate
domain.config["IDENTITY_TYPE"] = IdentityType.INTEGER.value
domain.domain_context().push()


@domain.aggregate
class User:
    user_id = Identifier(identifier=True)
    name = String(required=True)
    subscribed = Boolean(default=False)
