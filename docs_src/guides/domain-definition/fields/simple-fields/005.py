from datetime import datetime

from protean import Domain
from protean.fields import Date, String

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class Post:
    title = String(max_length=255)
    published_on = Date(default=lambda: datetime.today().date())
