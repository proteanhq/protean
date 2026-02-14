from protean import Domain
from protean.utils import IdentityType
from pydantic import Field

domain = Domain()

# Customize Identity Strategy and Type and activate
domain.config["IDENTITY_TYPE"] = IdentityType.INTEGER.value
domain.domain_context().push()


@domain.aggregate
class User:
    user_id: str = Field(json_schema_extra={"identifier": True})
    name: str
    subscribed: bool = False
