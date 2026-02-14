from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class UserProfile:
    name: Annotated[str, Field(max_length=30)] | None = None


print(UserProfile.meta_.schema_name)
# 'user_profile'
