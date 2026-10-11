# --8<-- [start:default]
from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)
    email: String(required=True, max_length=254)


# --8<-- [end:default]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        print(domain.repository_for(Person))
