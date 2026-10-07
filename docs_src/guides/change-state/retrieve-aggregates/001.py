from protean import Domain
from protean.fields import Integer, String
from protean.utils.query import Q

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)
    age: Integer(default=21)
    country: String(max_length=2)


# The custom repository is registered before `init`, so that
# `repository_for(Person)` returns it.
# --8<-- [start:repository]
@domain.repository(part_of=Person)
class PersonRepository:
    def adults_in_country(self, country_code):
        """Find all adults in the specified country."""
        return self.query.filter(age__gte=18, country=country_code).all().items

    def children_by_age(self, country_code=None):
        """Find all children ordered by age."""
        query = self.query.filter(age__lt=18)
        if country_code:
            query = query.filter(country=country_code)
        return query.order_by("age").all().items


# --8<-- [end:repository]


# --8<-- [start:seed]
domain.init(traverse=False)

# Activate the domain for the queries that follow
context = domain.domain_context()
context.push()

repository = domain.repository_for(Person)

for person in [
    Person(name="John Doe", age=38, country="CA"),
    Person(name="John Roe", age=41, country="US"),
    Person(name="Jane Doe", age=36, country="CA"),
    Person(name="Baby Doe", age=3, country="CA"),
    Person(name="Boy Doe", age=8, country="CA"),
    Person(name="Girl Doe", age=11, country="CA"),
]:
    repository.add(person)
# --8<-- [end:seed]


# --8<-- [start:exists_method]
# Inside a custom repository method
def has_adults_in_country(self, country: str) -> bool:
    return self.exists(Q(age__gte=18) & Q(country=country))


# --8<-- [end:exists_method]


# --8<-- [start:queryset]
queryset = repository.query
# --8<-- [end:queryset]

# --8<-- [start:q_and]
# People named "Doe" who are at least 18
people = repository.query.filter(Q(name__contains="Doe") & Q(age__gte=18)).all().items
# --8<-- [end:q_and]
adults_named_doe = people

# --8<-- [start:q_or]
# People who are under 5 OR over 40
people = repository.query.filter(Q(age__lt=5) | Q(age__gt=40)).all().items
# --8<-- [end:q_or]
under_5_or_over_40 = people

# --8<-- [start:q_not]
# Everyone except those in the US
people = repository.query.filter(~Q(country="US")).all().items
# --8<-- [end:q_not]
outside_us = people

# --8<-- [start:q_nested]
# (Adults in CA) OR (children in US)
people = (
    repository.query.filter(
        (Q(age__gte=18) & Q(country="CA")) | (Q(age__lt=18) & Q(country="US"))
    )
    .all()
    .items
)
# --8<-- [end:q_nested]
ca_adults_or_us_children = people

# --8<-- [start:q_mixed]
# People in CA who are either named "John Doe" or under age 5
people = (
    repository.query.filter(Q(name="John Doe") | Q(age__lt=5), country="CA").all().items
)
# --8<-- [end:q_mixed]
ca_john_doe_or_under_5 = people

# --8<-- [start:order_by_fields]
# Sort by country ascending, then age descending
people = repository.query.order_by(["country", "-age"]).all().items
# --8<-- [end:order_by_fields]
by_country_then_age = people

# --8<-- [start:limit]
# Limit to 10 records
limited_query = repository.query.limit(10).all()

# Remove limit entirely
unlimited_query = repository.query.limit(None).all()
# --8<-- [end:limit]


# --8<-- [start:get_page]
def get_page(self, page_number, page_size=10):
    """Get a specific page of results."""
    offset = (page_number - 1) * page_size
    return self.query.offset(offset).limit(page_size).all()


# --8<-- [end:get_page]


# --8<-- [start:pagination]
result = repository.query.offset(10).limit(10).all()

page = result.page  # Current page number (1-indexed)
page_size = result.page_size  # Number of items per page (alias for limit)
total_pages = result.total_pages  # Total number of pages
has_next = result.has_next  # True if more pages exist beyond the current one
has_prev = result.has_prev  # True if this is not the first page
# --8<-- [end:pagination]

# --8<-- [start:with_total]
# Only the rows are needed, so the separate count query is skipped
items = repository.query.filter(country="CA").all(with_total=False).items
# --8<-- [end:with_total]

# --8<-- [start:only]
records = repository.query.filter(country="CA").only("name", "age").all().items
# --8<-- [end:only]

# --8<-- [start:update]
count = repository.query.filter(country="CA", age__lt=18).update(country="XX")
# --8<-- [end:update]
updated_count = count

# --8<-- [start:delete]
count = repository.query.filter(country="XX").delete()
# --8<-- [end:delete]
deleted_count = count

# --8<-- [start:raw]
results = repository.query.raw('{"name": "John Doe", "age__gte": 18}')
# --8<-- [end:raw]

context.pop()
