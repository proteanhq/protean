# --8<-- [start:shared_table]
from protean import Domain
from protean.fields import String

domain = Domain(name="ReferenceDataSharedTable")


@domain.aggregate
class Currency:
    code: String(identifier=True, max_length=3)
    name: String(required=True)
    symbol: String(max_length=4)


@domain.database_model(part_of=Currency, schema_name="master_data")
class CurrencyModel:
    pass  # the shared physical table


@domain.aggregate
class Country:
    code: String(identifier=True, max_length=2)
    name: String(required=True)


@domain.database_model(part_of=Country, schema_name="master_data")
class CountryModel:
    pass  # same table, different concept


# --8<-- [end:shared_table]

domain.init(traverse=False)
