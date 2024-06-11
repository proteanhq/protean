import time

from protean import Domain
from protean.fields import Auto, String

domain = Domain(__file__, load_toml=False)


def gen_ids():
    return int(time.time() * 1000)


@domain.aggregate
class User:
    user_id = Auto(
        identifier=True,
        identity_strategy="function",
        identity_function=gen_ids,
        identity_type="integer",
    )
    name = String(required=True)
