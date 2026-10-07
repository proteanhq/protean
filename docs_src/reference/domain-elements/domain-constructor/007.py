import random

from protean import Domain


# --8<-- [start:identity_function]
def generate_id():
    return "custom-id-" + str(random.randint(1000, 9999))


domain = Domain(
    config={"identity_strategy": "function"},
    identity_function=generate_id,
)
# --8<-- [end:identity_function]
