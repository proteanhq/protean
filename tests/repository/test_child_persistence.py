import pytest

from protean.globals import current_domain

from .child_entities import Comment, Post, PostMeta


class TestHasOnePersistence:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Post)
        test_domain.register(PostMeta)
        test_domain.register(Comment)

    @pytest.fixture(autouse=True)
    def persist_post(self, test_domain, register_elements):
        post = test_domain.get_dao(Post).create(
            title="Test Post", slug="test-post", content="Do Re Mi Fa"
        )
        return post

    @pytest.fixture
    def persisted_post(self, test_domain):
        return test_domain.get_dao(Post).find_by(title="Test Post")

    def test_that_has_one_entity_can_be_added(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        meta = PostMeta(likes=1)
        persisted_post.post_meta = meta

        post_repo.add(persisted_post)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.post_meta is not None
        assert isinstance(refreshed_post.post_meta, PostMeta)
        assert refreshed_post.post_meta == meta

    def test_that_adding_another_has_one_entity_replaces_existing_child(
        self, persisted_post
    ):
        post_repo = current_domain.repository_for(Post)

        meta1 = PostMeta(likes=1)
        meta2 = PostMeta(likes=2)
        persisted_post.post_meta = meta1

        post_repo.add(persisted_post)

        post_to_alter = post_repo.get(persisted_post.id)
        post_to_alter.post_meta = meta2

        post_repo.add(post_to_alter)

        refreshed_post = post_repo.get(persisted_post.id)

        assert refreshed_post is not None
        assert refreshed_post.post_meta is not None
        assert isinstance(refreshed_post.post_meta, PostMeta)
        assert refreshed_post.post_meta == meta2

    def test_that_a_has_one_entity_can_be_removed(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        meta = PostMeta(likes=1)
        persisted_post.post_meta = meta

        post_repo.add(persisted_post)

        post_to_alter = post_repo.get(persisted_post.id)
        post_to_alter.post_meta = None

        post_repo.add(post_to_alter)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.post_meta is None


class TestHasManyPersistence:
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

    def test_that_a_has_many_entity_can_be_added(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        post_repo.add(persisted_post)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.comments is not None
        assert comment.id in [comment.id for comment in refreshed_post.comments]

    def test_that_multiple_has_many_entities_can_be_added(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        comment1 = Comment(content="So La Ti Do")
        comment2 = Comment(content="Do Re Mi Fa")
        persisted_post.add_comments(comment1)
        persisted_post.add_comments(comment2)

        post_repo.add(persisted_post)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.comments is not None
        assert len(refreshed_post.comments) == 2
        assert all(
            comment in [comment for comment in refreshed_post.comments]
            for comment in [comment1, comment2]
        )

    def test_that_a_has_many_entity_can_be_removed(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        post_repo.add(persisted_post)

        post_to_alter = post_repo.get(persisted_post.id)
        post_to_alter.remove_comments(comment)

        post_repo.add(post_to_alter)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.comments is not None
        assert len(refreshed_post.comments) == 0

    def test_that_a_has_many_entity_can_be_removed_from_among_many(
        self, persisted_post
    ):
        post_repo = current_domain.repository_for(Post)

        comment1 = Comment(content="So La Ti Do")
        comment2 = Comment(content="Do Re Mi Fa")
        persisted_post.add_comments(comment1)
        persisted_post.add_comments(comment2)

        post_repo.add(persisted_post)

        post_to_alter = post_repo.get(persisted_post.id)
        post_to_alter.remove_comments(comment1)

        post_repo.add(post_to_alter)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.comments is not None
        assert len(refreshed_post.comments) == 1
        assert comment2.id in [comment.id for comment in refreshed_post.comments]
