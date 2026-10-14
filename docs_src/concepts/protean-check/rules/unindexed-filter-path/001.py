# --8<-- [start:flagged]
from protean import Domain, Index
from protean.fields import Identifier, String

domain = Domain(name="app")


@domain.aggregate(indexes=[Index("status")])
class Order:
    order_id = Identifier(identifier=True)
    status = String(max_length=20)
    reference = String(max_length=40)  # not indexed


@domain.repository(part_of=Order)
class OrderRepository:
    def by_reference(self, reference):
        # filters `reference`, which no index covers -> UNINDEXED_FILTER_PATH
        return self._dao.filter(reference=reference)

    def open(self):
        # filters `status`, the leading column of Index("status") -> no finding
        return self._dao.filter(status="open")


# --8<-- [end:flagged]
