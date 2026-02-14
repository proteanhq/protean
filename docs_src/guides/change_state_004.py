from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)
    email: String(required=True, max_length=254)
    age: Integer(default=21)


@domain.repository(part_of=Person)  # (1)
class CustomPersonRepository:
    def find_by_email(self, email: str) -> Person:
        return self._dao.find_by(email=email)
