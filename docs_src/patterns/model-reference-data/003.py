# --8<-- [start:aggregate]
from protean import Domain, current_domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Boolean, Integer, String

domain = Domain(name="ReferenceDataCurrencies")


@domain.event(part_of="Currency")
class CurrencyDeactivated:
    code: String(required=True)


@domain.aggregate
class Currency:
    code: String(identifier=True, max_length=3)  # "USD" is the identity
    name: String(required=True)
    symbol: String(max_length=4)
    minor_units: Integer(default=2)  # 2 for USD, 0 for JPY
    is_active: Boolean(default=True)

    @invariant.post
    def code_must_be_iso_4217(self):
        if len(self.code) != 3 or not self.code.isalpha():
            raise ValidationError(
                {"code": ["Currency code must be a 3-letter ISO 4217 code"]}
            )

    def deactivate(self) -> None:
        self.is_active = False
        self.raise_(CurrencyDeactivated(code=self.code))


# --8<-- [end:aggregate]


# --8<-- [start:load_one]
def seed_currencies() -> None:
    repo = current_domain.repository_for(Currency)
    repo.add(Currency(code="USD", name="US Dollar", symbol="$"))
    repo.add(Currency(code="EUR", name="Euro", symbol="€"))
    repo.add(Currency(code="JPY", name="Japanese Yen", symbol="¥", minor_units=0))


def find_usd() -> Currency:
    repo = current_domain.repository_for(Currency)
    usd = repo.get("USD")  # the code IS the identity
    return usd


# --8<-- [end:load_one]


# --8<-- [start:repository]
@domain.repository(part_of=Currency)
class CurrencyRepository:
    def all_active(self) -> list[Currency]:
        return self.query.filter(is_active=True).all().items

    def as_map(self) -> dict[str, Currency]:
        """code → Currency, ready for validation or a dropdown."""
        return {c.code: c for c in self.all_active()}


# --8<-- [end:repository]


# --8<-- [start:consumer]
def currency_dropdown() -> list[Currency]:
    repo = current_domain.repository_for(Currency)
    return repo.all_active()  # list[Currency]


def validate_currency(code: str) -> Currency:
    repo = current_domain.repository_for(Currency)
    by_code = repo.as_map()  # {"USD": Currency(...), "EUR": ...}

    if code not in by_code:
        raise ValidationError({"currency": ["Unknown currency"]})
    return by_code[code]


# --8<-- [end:consumer]

domain.init(traverse=False)
