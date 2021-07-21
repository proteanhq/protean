import pytest

from .aggregate_elements import Comment, Post, PostMeta


class TestAggregatesWithEntities:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Post)
        test_domain.register(PostMeta)
        test_domain.register(Comment)

    @pytest.fixture
    def persisted_post(self, test_domain):
        post = test_domain.get_dao(Post).create(
            title="Test Post", slug="test-post", content="Do Re Mi Fa"
        )
        return post

    def test_that_an_entity_can_be_added(self, persisted_post):
        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        assert comment in persisted_post.comments

    def test_that_the_parent_is_associated_with_child_once_added_to_parent(
        self, persisted_post
    ):
        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        assert comment.post_id is not None

    def test_that_adding_an_existing_entity_does_not_create_duplicates(
        self, persisted_post
    ):
        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        assert comment in persisted_post.comments
        assert len(persisted_post.comments) == 1

        # Add the child object again
        persisted_post.add_comments(comment)

        assert comment in persisted_post.comments
        assert len(persisted_post.comments) == 1

    def test_that_an_entity_can_be_removed(self, persisted_post):
        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        assert comment in persisted_post.comments

        persisted_post.remove_comments(comment)
        assert comment not in persisted_post.comments

    def test_that_one_entity_amongst_many_can_be_removed(self, persisted_post):
        comment1 = Comment(content="So La Ti Do")
        comment2 = Comment(content="Sa Re Ga Ma")
        persisted_post.add_comments(comment1)
        persisted_post.add_comments(comment2)

        assert comment1 in persisted_post.comments
        assert comment2 in persisted_post.comments
        assert len(persisted_post.comments) == 2

        persisted_post.remove_comments(comment1)

        assert len(persisted_post.comments) == 1
        assert comment1 not in persisted_post.comments
        assert comment2 in persisted_post.comments
        assert comment2.id == persisted_post.comments[0].id

    def test_that_all_entities_can_be_removed(self, persisted_post):
        comment1 = Comment(content="So La Ti Do")
        comment2 = Comment(content="Sa Re Ga Ma")
        persisted_post.add_comments(comment1)
        persisted_post.add_comments(comment2)

        assert comment1 in persisted_post.comments
        assert comment2 in persisted_post.comments
        assert len(persisted_post.comments) == 2

        persisted_post.remove_comments([comment1, comment2])

        assert len(persisted_post.comments) == 0

    def test_conversion_of_enclosed_entity_values_to_dict(self, persisted_post):
        comment1 = Comment(content="So La Ti Do")
        comment2 = Comment(content="Sa Re Ga Ma")
        persisted_post.add_comments(comment1)
        persisted_post.add_comments(comment2)

        assert persisted_post.to_dict() == {
            "id": persisted_post.id,
            "title": "Test Post",
            "slug": "test-post",
            "content": "Do Re Mi Fa",
            "posted_at": str(persisted_post.posted_at),
            "comments": [
                {
                    "id": comment1.id,
                    "content": "So La Ti Do",
                    "commented_at": str(comment1.commented_at),
                },
                {
                    "id": comment2.id,
                    "content": "Sa Re Ga Ma",
                    "commented_at": str(comment2.commented_at),
                },
            ],
        }
