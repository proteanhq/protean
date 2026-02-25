# --8<-- [start:full]
from protean import Domain
from protean.fields import Integer, String

domain = Domain()
domain.config["databases"]["default"] = {
    "provider": "sqlite",
    "database_uri": "sqlite:///myapp.db",
}


@domain.aggregate
class Person:
    name: String(max_length=50, required=True)
    age: Integer()


domain.init()
with domain.domain_context():
    # Create database tables
    domain.providers["default"].decorate_model_class(
        domain.repository_for(Person)._database_model
    )

    # Use like any other provider
    person = Person(name="Alice", age=25)
    domain.repository_for(Person).add(person)
    retrieved = domain.repository_for(Person).get(person.id)
    assert retrieved.name == "Alice"
# --8<-- [end:full]
