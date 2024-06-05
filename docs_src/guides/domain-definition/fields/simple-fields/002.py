from protean import Domain
from protean.fields import String, Text

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class Book:
    title = String(max_length=255)
    content = Text(required=True)
