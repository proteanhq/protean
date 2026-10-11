# --8<-- [start:domain]
from protean import Domain
from protean.fields import String

domain = Domain(name="Catalogue")


@domain.aggregate
class SomeAggregate:
    name: String(max_length=50)


domain.init(traverse=False)
# --8<-- [end:domain]

# --8<-- [start:coded_exception]
from protean.exceptions import IncorrectUsageError

try:
    domain.view_for(SomeAggregate)
except IncorrectUsageError as exc:
    print(exc.code)  # "USAGE_NOT_A_PROJECTION"
    print(exc.codes)  # ["USAGE_NOT_A_PROJECTION"]
    print(exc.location)  # "Domain.view_for"
    print(exc.rationale)  # why it fired, from the registry
    print(exc.fix)  # how to fix it, from the registry
# --8<-- [end:coded_exception]
