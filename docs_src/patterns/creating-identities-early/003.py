from protean import Domain
from protean.fields import Auto, Float

domain = Domain(name="CreatingIdentitiesEarlyMeasurements")

# --8<-- [start:function]
import time


def gen_epoch_id():
    return int(time.time() * 1000)


@domain.aggregate
class Measurement:
    measurement_id: Auto(
        identifier=True,
        identity_strategy="function",
        identity_function=gen_epoch_id,
        identity_type="integer",
    )
    value: Float()


# --8<-- [end:function]
