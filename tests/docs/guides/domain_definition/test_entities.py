"""The example on the entities guide behaves as the page says."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_entities_guide_comment_links_to_its_post():
    example = load_example("guides/domain-definition/007.py")
    example.publishing.init(traverse=False)

    with example.publishing.domain_context():
        post = example.Post(name="Hello", created_on="2024-01-01")
        comment = example.Comment(content="Nice", post=post)

    assert comment.post_id == post.id
    assert example.Comment.meta_.part_of is example.Post
