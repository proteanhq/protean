from protean.fields import String
from tests.support.domains.test13.publishing13 import domain


@domain.aggregate
class User:
    first_name: String(max_length=50)
    last_name: String(max_length=50)
