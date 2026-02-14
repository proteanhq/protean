from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)
    email: String(required=True, max_length=254)


domain.init(traverse=False)
with domain.domain_context():
    person = Person(
        id="1",  # (1)
        name="John Doe",
        email="john.doe@localhost",
    )
    domain.repository_for(Person).add(person)
