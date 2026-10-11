# The page shows Version 2's import above its code, so it sits at the top here.
# --8<-- [start:version_2_import]
# Version 2
from protean import UnitOfWork

# --8<-- [end:version_2_import]
# isort: split
from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)
    email: String(required=True, max_length=254)


domain.init(traverse=False)

person = Person(id="1", name="John Doe", email="john.doe@localhost")

# --8<-- [start:version_1]
# Version 1
with domain.domain_context():
    domain.repository_for(Person).add(person)
# --8<-- [end:version_1]

person = Person(id="2", name="Jane Doe", email="jane.doe@localhost")

# --8<-- [start:version_2]
with domain.domain_context():
    with UnitOfWork():
        domain.repository_for(Person).add(person)
# --8<-- [end:version_2]
