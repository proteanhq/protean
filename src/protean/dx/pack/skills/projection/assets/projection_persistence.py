"""
Projection persistence and querying using the repository pattern.

This example demonstrates:
- Persisting projection records via domain.repository_for()
- Retrieving projection records by identifier
- Updating projection records
- Querying all records with _dao.query.all()
- Projection state tracking (is_new)
- Projections use the same repository pattern as aggregates

Usage:
    person = Person(person_id="1", first_name="John", last_name="Doe", age=25)
    domain.repository_for(Person).add(person)
    refreshed = domain.repository_for(Person).get("1")
"""

from protean import Domain
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()


@domain.projection
class Person:
    """Simple person projection for demonstrating persistence.

    Uses person_id as the explicit identifier field.
    """

    person_id: Identifier(identifier=True)
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50)
    age: Integer(default=21)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create and persist a projection record
        person = Person(person_id="1", first_name="John", last_name="Doe", age=25)
        print(f"State is new: {person.state_.is_new}")
        assert person.state_.is_new is True

        domain.repository_for(Person).add(person)

        # Retrieve the record
        refreshed = domain.repository_for(Person).get("1")
        print(f"Retrieved: {refreshed.first_name} {refreshed.last_name}")
        assert refreshed.first_name == "John"
        assert refreshed.age == 25

        # Update the record
        refreshed.first_name = "Jane"
        domain.repository_for(Person).add(refreshed)

        # Verify the update
        updated = domain.repository_for(Person).get("1")
        print(f"Updated: {updated.first_name} {updated.last_name}")
        assert updated.first_name == "Jane"
        assert updated.last_name == "Doe"

        # Create multiple records and query all
        person2 = Person(person_id="2", first_name="Alice", last_name="Smith", age=30)
        domain.repository_for(Person).add(person2)

        all_people = domain.repository_for(Person)._dao.query.all()
        print(f"Total people: {len(all_people.items)}")
        assert len(all_people.items) == 2

        print("Projection persistence working correctly!")
