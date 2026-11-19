"""A ``HasOne`` child that is changed, assigned again to the same field, and
then loses its changed flag before the parent is saved is still written."""

import pytest

from protean.utils.globals import current_domain

from .child_entities import Comment, Post, PostMeta


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(PostMeta, part_of=Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.init(traverse=False)


@pytest.mark.database
@pytest.mark.usefixtures("db")
def test_reassigned_child_is_saved_after_its_changed_flag_clears(test_domain):
    post_repo = current_domain.repository_for(Post)
    post = Post(title="Test", slug="test", content="Hello")
    post.post_meta = PostMeta(likes=10)
    post_repo.add(post)

    post = post_repo.get(post.id)
    meta = post.post_meta
    meta.likes = 42
    post.post_meta = meta
    meta.state_.mark_saved()

    post_repo.add(post)

    assert post_repo.get(post.id).post_meta.likes == 42
