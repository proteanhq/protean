"""``DAO.outside_uow()`` returns a new DAO that works outside the active Unit
of Work, and leaves the DAO it is called on inside it."""

from protean import UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.fields import String


class Note(BaseAggregate):
    body = String(max_length=100)


def _repo(test_domain):
    test_domain.register(Note)
    test_domain.init(traverse=False)
    return test_domain.repository_for(Note)


def test_outside_uow_returns_another_dao(test_domain):
    repo = _repo(test_domain)
    assert repo._dao.outside_uow() is not repo._dao


def test_reads_through_the_dao_join_the_uow_after_an_outside_uow_call(test_domain):
    repo = _repo(test_domain)
    repo._dao.outside_uow()

    with UnitOfWork():
        note = Note(body="draft")
        repo.add(note)
        assert repo._dao.get(note.id).body == "draft"
        assert [item.id for item in repo._dao.query.all().items] == [note.id]
        # The write joined the Unit of Work, so nothing is committed yet.
        assert repo._dao.outside_uow().query.all().items == []


def test_reads_through_the_returned_dao_skip_the_uow_writes(test_domain):
    repo = _repo(test_domain)

    with UnitOfWork():
        note = Note(body="draft")
        repo.add(note)
        outside = repo._dao.outside_uow()
        assert outside.query.all().items == []
        assert outside.query.filter(id=note.id).all().items == []
