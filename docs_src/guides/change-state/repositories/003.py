from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)
    email: String(required=True, max_length=254)
    age: Integer(default=21)
    country: String(max_length=2)


# --8<-- [start:custom_queries]
from protean.utils.query import Q


@domain.repository(part_of=Person)
class PersonRepository:
    def adults_in_country(self, country_code: str) -> list:
        return self.find(Q(age__gte=18, country=country_code)).items

    def find_by_email(self, email: str) -> Person:
        return self.find_by(email=email)

    def has_adults(self) -> bool:
        return self.exists(Q(age__gte=18))


# --8<-- [end:custom_queries]


# --8<-- [start:errors]
from protean.exceptions import ObjectNotFoundError, TooManyObjectsError


def get_person(person_id: str) -> Person | None:
    repo = domain.repository_for(Person)

    # Raises ObjectNotFoundError if no aggregate matches the identity
    try:
        return repo.get(person_id)
    except ObjectNotFoundError:
        return None


def find_person(email: str) -> Person | None:
    repo = domain.repository_for(Person)

    # Raises ObjectNotFoundError if no match, TooManyObjectsError if multiple
    try:
        return repo.find_by(email=email)
    except ObjectNotFoundError:
        return None
    except TooManyObjectsError as exc:
        raise ValueError(f"More than one person uses {email}") from exc


# --8<-- [end:errors]


# --8<-- [start:exists]
def check_email_is_free(email: str) -> None:
    repo = domain.repository_for(Person)

    if repo.exists(Q(email=email)):
        raise ValueError("Email already taken")


# --8<-- [end:exists]


# --8<-- [start:get_or_none]
def referrer_name(referred_by: str) -> str:
    repo = domain.repository_for(Person)

    # Returns None instead of raising ObjectNotFoundError
    person = repo.get_or_none(referred_by)
    if person is None:
        return "nobody"
    return person.name


# --8<-- [end:get_or_none]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        print(get_person("nonexistent-id"))  # None
        print(referrer_name("nonexistent-id"))  # nobody
