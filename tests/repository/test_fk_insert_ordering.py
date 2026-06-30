"""Tests for the parent-before-child flush cascade in ``repository.add``.

Protean does not emit SQLAlchemy ``ForeignKey``/``relationship`` metadata for
``Reference`` fields, so the ORM cannot order parent-before-child inserts at
commit-time flush on its own. ``_do_add`` / ``_sync_children`` therefore call
``BaseDAO._flush()`` after each parent level so the parent row materializes in
the transaction before its FK-referencing children are written.

The flush-ordering assertions here are provider-agnostic: they spy on the
no-op ``_flush`` hook of the in-memory DAO, so they run as core tests without
any database. Test cases against a real immediate-FK backend live below behind
``@pytest.mark.database``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany, Integer, Reference, String
from protean.utils.globals import current_domain

from .child_entities import Comment, Member, Post, PostMeta, Team


class Branch(BaseEntity):
    name: String(required=True)
    leaves = HasMany("tests.repository.test_fk_insert_ordering.Leaf")

    tree = Reference("tests.repository.test_fk_insert_ordering.Tree")


class Leaf(BaseEntity):
    color: String(required=True)

    branch = Reference("tests.repository.test_fk_insert_ordering.Branch")


class Tree(BaseAggregate):
    name: String(required=True)
    branches = HasMany("tests.repository.test_fk_insert_ordering.Branch")


class Plain(BaseAggregate):
    """Aggregate with no child associations."""

    name: String(required=True)
    count: Integer(default=0)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(PostMeta, part_of=Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.register(Team)
    test_domain.register(Member, part_of=Team)
    test_domain.register(Tree)
    test_domain.register(Branch, part_of=Tree)
    test_domain.register(Leaf, part_of=Branch)
    test_domain.register(Plain)
    test_domain.init(traverse=False)


@pytest.fixture
def flush_spy(monkeypatch):
    """Count ``_flush`` calls on every DAO routed through a repository.

    Returns a dict mapping the spy to a mutable counter so individual tests can
    assert how many flushes the cascade issued.
    """
    from protean.port.dao import BaseDAO

    counter = {"count": 0}
    original = BaseDAO._flush

    def spy(self):
        counter["count"] += 1
        return original(self)

    monkeypatch.setattr(BaseDAO, "_flush", spy)
    return counter


class TestFlushCascadeOrdering:
    def test_single_level_children_trigger_one_flush(self, flush_spy):
        team = Team(name="Reds")
        team.add_members(Member(name="Alice"))
        team.add_members(Member(name="Bob"))

        current_domain.repository_for(Team).add(team)

        # One flush: after the root Team is saved, before the Member inserts.
        assert flush_spy["count"] == 1

    def test_has_one_child_triggers_one_flush(self, flush_spy):
        post = Post(title="T", slug="t", content="body")
        post.post_meta = PostMeta(likes=1)

        current_domain.repository_for(Post).add(post)

        assert flush_spy["count"] == 1

    def test_two_level_children_trigger_flush_per_level(self, flush_spy):
        tree = Tree(name="Oak")
        branch = Branch(name="north")
        branch.add_leaves(Leaf(color="green"))
        tree.add_branches(branch)

        current_domain.repository_for(Tree).add(tree)

        # Flush after root Tree (before Branch insert) and again before
        # descending into the Branch's Leaf grandchildren.
        assert flush_spy["count"] == 2

    def test_childless_aggregate_does_not_flush(self, flush_spy):
        current_domain.repository_for(Plain).add(Plain(name="solo"))

        assert flush_spy["count"] == 0


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestForeignKeyInsertOrdering:
    """End-to-end persistence against the configured database backend."""

    def test_parent_with_has_many_children_commits(self):
        team = Team(name="Blues")
        team.add_members(Member(name="Carol"))
        team.add_members(Member(name="Dave"))

        current_domain.repository_for(Team).add(team)

        refreshed = current_domain.repository_for(Team).get(team.id)
        assert refreshed is not None
        assert len(refreshed.members) == 2

    def test_parent_with_has_one_child_commits(self):
        post = Post(title="T", slug="t", content="body")
        post.post_meta = PostMeta(likes=5)

        current_domain.repository_for(Post).add(post)

        refreshed = current_domain.repository_for(Post).get(post.id)
        assert refreshed is not None
        assert refreshed.post_meta is not None
        assert refreshed.post_meta.likes == 5

    def test_grandchild_ordering_commits(self):
        tree = Tree(name="Oak")
        branch = Branch(name="north")
        branch.add_leaves(Leaf(color="green"))
        tree.add_branches(branch)

        current_domain.repository_for(Tree).add(tree)

        refreshed = current_domain.repository_for(Tree).get(tree.id)
        assert refreshed is not None
        assert len(refreshed.branches) == 1
        assert len(refreshed.branches[0].leaves) == 1
