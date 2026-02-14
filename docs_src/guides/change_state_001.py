from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    name: Annotated[str, Field(max_length=50)]
    email: Annotated[str, Field(max_length=254)]


domain.init(traverse=False)
with domain.domain_context():
    person = Person(
        id="1",  # (1)
        name="John Doe",
        email="john.doe@localhost",
    )
    domain.repository_for(Person).add(person)
