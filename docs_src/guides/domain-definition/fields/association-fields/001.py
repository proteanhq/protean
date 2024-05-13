from protean import Domain
from protean.fields import HasOne, String

domain = Domain(__file__)


@domain.aggregate
class Book:
    title = String(required=True, max_length=100)
    author = HasOne("Author")


@domain.entity(aggregate_cls="Book")
class Author:
    name = String(required=True, max_length=50)
