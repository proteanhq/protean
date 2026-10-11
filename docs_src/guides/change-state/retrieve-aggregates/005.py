from protean import Domain
from protean.fields import Integer, String

domain = Domain()


# --8<-- [start:index]
from protean import Index


@domain.aggregate(indexes=[Index("country", "age", desc=("age",))])
class Customer:
    country = String(max_length=2)
    age = Integer()


# --8<-- [end:index]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        repo = domain.repository_for(Customer)
        repo.add(Customer(country="US", age=30))
        repo.add(Customer(country="US", age=45))
        print([c.age for c in repo.query.filter(country="US").order_by("-age").all()])
