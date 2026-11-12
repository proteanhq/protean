# --8<-- [start:imports]
from protean import Domain, current_domain
from protean.core.projector import on
from protean.fields import Boolean, String

# --8<-- [end:imports]

domain = Domain(name="ReferenceDataCatalog")
domain.config["event_processing"] = "sync"
domain.config["caches"]["catalog"] = {"provider": "memory"}


# --8<-- [start:write_side]
@domain.event(part_of="Currency")
class CurrencyAdded:
    code: String(required=True)
    name: String(required=True)
    symbol: String(max_length=4)


@domain.event(part_of="Currency")
class CurrencyDeactivated:
    code: String(required=True)


@domain.aggregate
class Currency:
    code: String(identifier=True, max_length=3)
    name: String(required=True)
    symbol: String(max_length=4)
    is_active: Boolean(default=True)

    @classmethod
    def add(cls, code: str, name: str, symbol: str) -> "Currency":
        currency = cls(code=code, name=name, symbol=symbol)
        currency.raise_(CurrencyAdded(code=code, name=name, symbol=symbol))
        return currency

    def deactivate(self) -> None:
        self.is_active = False
        self.raise_(CurrencyDeactivated(code=self.code))


# --8<-- [end:write_side]


# --8<-- [start:projector]
@domain.projection(cache="catalog")
class CurrencyOption:
    code: String(identifier=True)
    name: String(required=True)
    symbol: String(max_length=4)


@domain.projector(projector_for=CurrencyOption, aggregates=[Currency])
class CurrencyCatalogProjector:
    @on(CurrencyAdded)
    def add_option(self, event: CurrencyAdded) -> None:
        cache = current_domain.cache_for(CurrencyOption)
        cache.add(CurrencyOption(code=event.code, name=event.name, symbol=event.symbol))

    @on(CurrencyDeactivated)
    def remove_option(self, event: CurrencyDeactivated) -> None:
        cache = current_domain.cache_for(CurrencyOption)
        cache.remove_by_key(cache.key_for(CurrencyOption, event.code))


# --8<-- [end:projector]

domain.init(traverse=False)
