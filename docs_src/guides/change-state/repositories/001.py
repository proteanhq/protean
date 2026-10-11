# --8<-- [start:reporting]
from protean import Domain
from protean.fields import Boolean, String

domain = Domain(
    config={
        "databases": {
            "default": {"provider": "memory"},
            "reporting": {"provider": "memory"},
        }
    }
)


@domain.aggregate(provider="reporting")
class Person:
    name: String(required=True, max_length=50)
    active: Boolean(default=True)


@domain.repository(part_of=Person, database="memory")
class PersonReportingRepository:
    def active_users_summary(self) -> list:
        return self.query.filter(active=True).all().items


# --8<-- [end:reporting]

if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        repo = domain.repository_for(Person)
        repo.add(Person(name="John Doe"))
        repo.add(Person(name="Jane Doe", active=False))
        print([person.name for person in repo.active_users_summary()])
