"""Elasticsearch takes the portable claim, which has no lock to hold across
its read and its guarded update. Two claimers that read the same row both send
a guarded ``update_by_query``. Elasticsearch applies at most one of them: the
other matches no row and claims nothing, or hits a version conflict that the
adapter raises as ``DatabaseError``."""

import threading
from uuid import uuid4

import pytest

from protean import Q
from protean.adapters.repository.elasticsearch import ElasticsearchDAO
from protean.exceptions import DatabaseError

from .elements import Person


@pytest.mark.elasticsearch
class TestPortableClaimRace:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.init(traverse=False)

    def test_a_row_is_claimed_at_most_once(self, test_domain, monkeypatch):
        tag = f"race{uuid4().hex}"
        person = test_domain.repository_for(Person)._dao.create(
            first_name="Athos", last_name=tag, age=0
        )
        meet = threading.Barrier(2, timeout=10)
        update_all = ElasticsearchDAO._update_all

        def update_after_meeting(self, criteria, *args, **kwargs):
            # Both claimers have read the row before either updates it.
            meet.wait()
            return update_all(self, criteria, *args, **kwargs)

        # Patched on the class: each repository_for call builds a new DAO.
        monkeypatch.setattr(ElasticsearchDAO, "_update_all", update_after_meeting)
        outcomes: dict[int, object] = {}

        def worker(idx: int) -> None:
            with test_domain.domain_context():
                dao = test_domain.repository_for(Person)._dao
                try:
                    rows = dao._claim(Q(last_name=tag, age=0), {"age": 1}, limit=1)
                    outcomes[idx] = [row.id for row in rows]
                except DatabaseError as exc:
                    outcomes[idx] = exc

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not any(thread.is_alive() for thread in threads)

        claims = [o for o in outcomes.values() if o == [person.id]]
        losers = [o for o in outcomes.values() if o != [person.id]]
        assert len(outcomes) == 2
        assert len(claims) <= 1
        assert all(o == [] or isinstance(o, DatabaseError) for o in losers)
        assert test_domain.repository_for(Person).get(person.id).age == 1
