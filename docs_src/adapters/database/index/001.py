# --8<-- [start:full]
from protean import Domain
from protean.fields import Integer, String
from protean.port.provider import DatabaseCapabilities

domain = Domain(name="Capabilities")


@domain.aggregate
class User:
    name: String(max_length=50, required=True)
    age: Integer(required=True)


domain.init(traverse=False)

with domain.domain_context():
    domain.repository_for(User).add(User(name="Ada", age=36))
    domain.repository_for(User).add(User(name="Tim", age=17))

    # Get the default provider
    provider = domain.providers["default"]

    # Check for a single capability
    if provider.has_capability(DatabaseCapabilities.RAW_QUERIES):
        # The query language is the provider's own. The memory provider
        # takes JSON filter criteria; a SQL provider takes SQL.
        results = provider.raw('{"age__gt": 21}')

    # Check for all of multiple capabilities (AND logic)
    if provider.has_all_capabilities(
        DatabaseCapabilities.NATIVE_JSON | DatabaseCapabilities.NATIVE_ARRAY
    ):
        # Use native JSON and array columns
        ...

    # Check for any of multiple capabilities (OR logic)
    if provider.has_any_capability(
        DatabaseCapabilities.TRANSACTIONS | DatabaseCapabilities.SIMULATED_TRANSACTIONS
    ):
        # Some form of transaction support is available
        ...
# --8<-- [end:full]
