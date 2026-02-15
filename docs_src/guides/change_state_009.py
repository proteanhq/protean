from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)
    email: String(required=True, max_length=254)
    age: Integer(default=21)
    country: String(max_length=2)


@domain.repository(part_of=Person)  # (1)!
class PersonRepository:
    def adults(self) -> list:  # (2)!
        """Find all adults."""
        return self._dao.query.filter(age__gte=18).all().items

    def find_by_email(self, email: str) -> Person:
        """Find a person by email address."""
        return self._dao.find_by(email=email)

    def by_country(self, country_code: str) -> list:
        """Find all people in a given country."""
        return self._dao.query.filter(country=country_code).all().items
