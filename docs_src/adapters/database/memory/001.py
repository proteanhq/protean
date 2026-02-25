# --8<-- [start:full]
from protean import Domain
from protean.fields import Integer, String

domain = Domain()

# Memory is the default provider -- no configuration needed
domain.config["databases"]["default"] = {
    "provider": "memory",
}


@domain.aggregate
class Person:
    name: String(max_length=50, required=True)
    age: Integer()


domain.init()
with domain.domain_context():
    # Create
    person = Person(name="John", age=30)
    domain.repository_for(Person).add(person)

    # Read
    retrieved = domain.repository_for(Person).get(person.id)
    assert retrieved.name == "John"

    # Update
    retrieved.age = 31
    domain.repository_for(Person).add(retrieved)

    # Delete
    domain.repository_for(Person).remove(retrieved)
# --8<-- [end:full]
