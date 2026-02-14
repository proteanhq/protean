from protean import Domain
from protean.fields import String, Text

domain = Domain()


@domain.aggregate
class Book:
    title = String(max_length=255)
    content = Text(required=True)
