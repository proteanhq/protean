import pytest

from protean.core.unit_of_work import UnitOfWork

from .aggregate_elements import Comment, Post, PostMeta, PostRepository


class TestUnitOfWorkRegistration:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Post)
        test_domain.register(PostMeta)
        test_domain.register(Comment)

        test_domain.register(PostRepository, aggregate_cls=Post)

        yield

    @pytest.fixture
    def persisted_post(self, test_domain):
        post = test_domain.get_dao(Post).create(
            title="Test Post", slug="test-post", content="Do Re Mi Fa"
        )
        return post

    def test_that_an_entity_can_be_added_within_uow(self, test_domain, persisted_post):
        repo = test_domain.repository_for(Post)

        with UnitOfWork():
            comment = Comment(content="So La Ti Do")
            persisted_post.add_comments(comment)

            repo = test_domain.repository_for(Post)
            repo.add(persisted_post)

            # FIXME Refactor `outside_uow` to be a global thread variable
            # post_dao = test_domain.get_dao(Post)
            # assert len(post_dao.outside_uow().get(persisted_post.id).comments) == 0

        post = repo.get(persisted_post.id)
        assert len(post.comments) == 1
        assert post.comments[0].content == "So La Ti Do"

    def test_that_an_entity_can_be_updated_within_uow(
        self, test_domain, persisted_post
    ):
        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        repo = test_domain.repository_for(Post)
        repo.add(persisted_post)

        post = repo.get(persisted_post.id)
        assert post.comments[0].content == "So La Ti Do"

        with UnitOfWork():
            comment = persisted_post.comments[0]
            comment.content = "Pa Da Ni Sa"
            persisted_post.add_comments(comment)

            repo = test_domain.repository_for(Post)
            repo.add(persisted_post)

            # FIXME Refactor `outside_uow` to be a global thread variable
            # assert comment.id in uow.changes_to_be_committed['default']['UPDATED']

        post = repo.get(persisted_post.id)
        assert post.comments[0].content == "Pa Da Ni Sa"

    def test_that_an_entity_can_be_removed_within_uow(
        self, test_domain, persisted_post
    ):
        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        repo = test_domain.repository_for(Post)
        repo.add(persisted_post)

        with UnitOfWork():
            comment = persisted_post.comments[0]
            persisted_post.remove_comments(comment)

            repo = test_domain.repository_for(Post)
            repo.add(persisted_post)

            # FIXME Refactor `outside_uow` to be a global thread variable
            # assert comment.id in uow.changes_to_be_committed['default']['REMOVED']

        post = repo.get(persisted_post.id)
        assert len(post.comments) == 0
