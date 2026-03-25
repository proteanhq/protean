from protean.domain import Domain
from protean.fields.simple import String

domain = Domain(name="TEST7")


@domain.aggregate
class Article:
    title = String(max_length=100, required=True)
