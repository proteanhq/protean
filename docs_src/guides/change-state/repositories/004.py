from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)


# --8<-- [start:repository_for]
domain.init(traverse=False)

with domain.domain_context():
    repo = domain.repository_for(Person)
    repo.add(Person(id="42", name="John Doe"))

    person = repo.get("42")
# --8<-- [end:repository_for]

# --8<-- [start:dao_delete]
repo = domain.repository_for(Person)
repo._dao.delete(person)
# --8<-- [end:dao_delete]
