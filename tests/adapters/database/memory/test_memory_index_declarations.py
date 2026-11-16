"""The in-memory adapter accepts index declarations.

Indexes are a persistence optimization that only SQL adapters render as DDL, so
non-DDL stores accept ``indexes=`` declarations without error and persist/query
as if the (non-unique) indexes were absent. Unique indexes are the exception:
the memory store enforces them for fidelity — see
``test_memory_unique_index_enforcement.py``.
"""

from protean import Index
from protean.core.aggregate import BaseAggregate
from protean.fields import String


def test_memory_adapter_persists_and_queries_with_indexes_declared(test_domain):
    @test_domain.aggregate(indexes=[Index("status"), Index("ref", unique=True)])
    class Job(BaseAggregate):
        ref = String(max_length=20, identifier=True)
        status = String(max_length=20)

    test_domain.init(traverse=False)

    repo = test_domain.repository_for(Job)
    repo.add(Job(ref="J1", status="pending"))
    repo.add(Job(ref="J2", status="done"))

    # Index declarations are inert for the memory store: get and filter work.
    assert repo.get("J1").status == "pending"
    matched = repo.query.filter(status="pending").all().items
    assert len(matched) == 1
    assert matched[0].ref == "J1"
