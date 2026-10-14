from protean import Domain, Index
from protean.fields import Identifier, String

domain = Domain(name="app")


# --8<-- [start:suppressed]
@domain.aggregate(
    indexes=[Index("status")],
    suppress_checks=["UNINDEXED_FILTER_PATH"],
)
class Order:
    order_id = Identifier(identifier=True)
    status = String(max_length=20)
    reference = String(max_length=40)


# --8<-- [end:suppressed]


@domain.repository(part_of=Order)
class OrderRepository:
    def by_reference(self, reference):
        return self._dao.filter(reference=reference)

    def open(self):
        return self._dao.filter(status="open")
