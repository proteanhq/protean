from protean.domain import Domain
from protean.fields import List, String

domain = Domain(__name__)


def standard_topics():
    return ["Music", "Cinema", "Politics"]


@domain.aggregate
class Adult:
    name = String(max_length=255)
    topics = List(default=standard_topics)
