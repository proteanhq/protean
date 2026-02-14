from protean import Domain
from protean.utils.globals import current_domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class User:
    first_name: Annotated[str, Field(max_length=50)] | None = None
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int | None = None


domain.init(traverse=False)


with domain.domain_context():
    # Access an active, connected instance of User Repository
    user_repo = current_domain.repository_for(User)
