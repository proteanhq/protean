"""Run the examples on ``docs/patterns/track-audit-fields.md``."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    module = load_example("patterns/track-audit-fields/001.py")
    with module.domain.domain_context():
        yield module


def test_an_unsaved_article_has_no_audit_values(example):
    article = example.Article(title="Draft", body="...")

    assert article.created_at is None
    assert article.updated_at is None
    assert article.created_by is None
    assert article.updated_by is None


def test_saving_in_a_context_stamps_the_acting_user(example):
    example.publish_hello()

    articles = example.domain.repository_for(example.Article).query.all().items
    assert len(articles) == 1
    (article,) = articles
    assert article.title == "Hello"
    assert article.created_by == "alice"
    assert article.updated_by == "alice"
    assert article.created_at is not None
    assert article.updated_at is not None


def test_create_stamps_both_timestamps_and_users(example):
    stored, _ = example.create_then_update()

    assert stored.title == "Draft"
    assert stored.created_at is not None
    assert stored.updated_at is not None
    assert stored.created_by == "alice"
    assert stored.updated_by == "alice"


def test_update_keeps_the_creation_values_and_refreshes_the_update_values(example):
    stored, final = example.create_then_update()

    assert final.title == "Published"
    assert final.created_at == stored.created_at
    assert final.created_by == "alice"
    assert final.updated_at > stored.updated_at
    assert final.updated_by == "bob"


def test_saving_without_a_user_leaves_the_audit_users_empty(example):
    repo = example.domain.repository_for(example.Article)
    article = example.Article(title="Anonymous", body="...")
    repo.add(article)

    stored = repo.get(article.id)
    assert stored.created_by is None
    assert stored.updated_by is None
    assert stored.created_at is not None
