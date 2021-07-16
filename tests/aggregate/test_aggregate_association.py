import mock
import pytest

from .elements import (
    Account,
    AccountVia,
    AccountViaWithReference,
    Author,
    Comment,
    CommentVia,
    CommentViaWithReference,
    Post,
    PostVia,
    PostViaWithReference,
    Profile,
    ProfileVia,
    ProfileViaWithReference,
)


class TestHasOne:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(Author)
        test_domain.register(AccountVia)
        test_domain.register(AccountViaWithReference)
        test_domain.register(Post)
        test_domain.register(Profile)
        test_domain.register(ProfileVia)
        test_domain.register(ProfileViaWithReference)

    def test_successful_initialization_of_entity_with_has_one_association(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.get_dao(Account).save(account)
        author = Author(first_name="John", last_name="Doe", account=account)
        test_domain.get_dao(Author).save(author)

        assert all(key in author.__dict__ for key in ["account", "account_email"])
        assert author.account.email == account.email
        assert author.account_email == account.email

        refreshed_account = test_domain.get_dao(Account).get(account.email)
        assert refreshed_account.author.id == author.id
        assert refreshed_account.author == author

    def test_successful_has_one_initialization_with_a_class_containing_via_and_no_reference(
        self, test_domain
    ):
        account = AccountVia(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.get_dao(AccountVia).save(account)
        profile = ProfileVia(
            profile_id="12345", about_me="Lorem Ipsum", account_email=account.email
        )
        test_domain.get_dao(ProfileVia).save(profile)

        refreshed_account = test_domain.get_dao(AccountVia).get(account.email)
        assert refreshed_account.profile == profile

    def test_successful_has_one_initialization_with_a_class_containing_via_and_reference(
        self, test_domain
    ):
        account = AccountViaWithReference(
            email="john.doe@gmail.com", password="a1b2c3", username="johndoe"
        )
        test_domain.get_dao(AccountViaWithReference).save(account)
        profile = ProfileViaWithReference(about_me="Lorem Ipsum", ac=account)
        test_domain.get_dao(ProfileViaWithReference).save(profile)

        refreshed_account = test_domain.get_dao(AccountViaWithReference).get(
            account.email
        )
        assert refreshed_account.profile == profile

    @mock.patch("protean.core.field.association.Association._fetch_objects")
    def test_that_subsequent_access_after_first_retrieval_do_not_fetch_record_again(
        self, mock, test_domain
    ):
        account = AccountViaWithReference(
            email="john.doe@gmail.com", password="a1b2c3", username="johndoe"
        )
        test_domain.get_dao(AccountViaWithReference).save(account)
        profile = ProfileViaWithReference(about_me="Lorem Ipsum", ac=account)
        test_domain.get_dao(ProfileViaWithReference).save(profile)

        mock.return_value = profile

        refreshed_account = test_domain.get_dao(AccountViaWithReference).get(
            account.email
        )
        for _ in range(3):
            getattr(refreshed_account, "profile")
        assert (
            mock.call_count == 0
        )  # This is because `profile` would have been loaded when account was fetched


class TestHasMany:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Post)
        test_domain.register(PostVia)
        test_domain.register(PostViaWithReference)
        test_domain.register(Comment)
        test_domain.register(CommentVia)
        test_domain.register(CommentViaWithReference)

    @pytest.fixture
    def persisted_post(self, test_domain):
        post = test_domain.get_dao(Post).create(
            title="Test Post", slug="test-post", content="Do Re Mi Fa"
        )
        return post

    def test_successful_initialization_of_entity_with_has_many_association(
        self, test_domain
    ):
        post = Post(content="Lorem Ipsum")
        test_domain.repository_for(Post).add(post)

        comment1 = Comment(id=101, content="First Comment")
        comment2 = Comment(id=102, content="Second Comment")

        post.add_comments(comment1)
        post.add_comments(comment2)
        test_domain.repository_for(Post).add(post)

        refreshed_post = test_domain.repository_for(Post).get(post.id)
        assert len(refreshed_post.comments) == 2
        assert "comments" in refreshed_post.__dict__  # Available after access
        assert refreshed_post.comments[0].post_id == post.id
        assert refreshed_post.comments[1].post_id == post.id

        assert isinstance(refreshed_post.comments, list)
        assert all(
            comment.id in [101, 102] for comment in refreshed_post.comments
        )  # `__iter__` magic here

    def test_adding_multiple_associations_at_the_same_time(self, test_domain):
        post = Post(content="Lorem Ipsum")
        test_domain.repository_for(Post).add(post)

        comment1 = Comment(id=101, content="First Comment")
        comment2 = Comment(id=102, content="Second Comment")

        post.add_comments([comment1, comment2])
        test_domain.repository_for(Post).add(post)

        refreshed_post = test_domain.repository_for(Post).get(post.id)
        assert len(refreshed_post.comments) == 2
        assert "comments" in refreshed_post.__dict__  # Available after access
        assert refreshed_post.comments[0].post_id == post.id
        assert refreshed_post.comments[1].post_id == post.id

        assert isinstance(refreshed_post.comments, list)
        assert all(
            comment.id in [101, 102] for comment in refreshed_post.comments
        )  # `__iter__` magic here

    def test_successful_has_one_initialization_with_a_class_containing_via_and_no_reference(
        self, test_domain
    ):
        post = PostVia(content="Lorem Ipsum")
        test_domain.get_dao(PostVia).save(post)
        comment1 = CommentVia(id=101, content="First Comment", posting_id=post.id)
        comment2 = CommentVia(id=102, content="First Comment", posting_id=post.id)
        test_domain.get_dao(CommentVia).save(comment1)
        test_domain.get_dao(CommentVia).save(comment2)

        assert comment1.posting_id == post.id
        assert comment2.posting_id == post.id

        refreshed_post = test_domain.get_dao(PostVia).get(post.id)
        assert len(refreshed_post.comments) == 2
        assert "comments" in refreshed_post.__dict__  # Available after access

        assert isinstance(refreshed_post.comments, list)
        assert all(
            comment.id in [101, 102] for comment in refreshed_post.comments
        )  # `__iter__` magic here

    def test_successful_has_one_initialization_with_a_class_containing_via_and_reference(
        self, test_domain
    ):
        post = PostViaWithReference(content="Lorem Ipsum")
        test_domain.get_dao(PostViaWithReference).save(post)
        comment1 = CommentViaWithReference(
            id=101, content="First Comment", posting=post
        )
        comment2 = CommentViaWithReference(
            id=102, content="First Comment", posting=post
        )
        test_domain.get_dao(CommentViaWithReference).save(comment1)
        test_domain.get_dao(CommentViaWithReference).save(comment2)

        assert comment1.posting_id == post.id
        assert comment2.posting_id == post.id

        refreshed_post = test_domain.get_dao(PostViaWithReference).get(post.id)
        assert len(refreshed_post.comments) == 2
        assert "comments" in refreshed_post.__dict__  # Available after access

        assert isinstance(refreshed_post.comments, list)
        assert all(
            comment.id in [101, 102] for comment in refreshed_post.comments
        )  # `__iter__` magic here

    def test_that_subsequent_access_after_first_retrieval_do_not_fetch_record_again(
        self, test_domain
    ):
        post = PostViaWithReference(content="Lorem Ipsum")
        test_domain.get_dao(PostViaWithReference).save(post)
        comment1 = CommentViaWithReference(
            id=101, content="First Comment", posting=post
        )
        comment2 = CommentViaWithReference(
            id=102, content="First Comment", posting=post
        )
        test_domain.get_dao(CommentViaWithReference).save(comment1)
        test_domain.get_dao(CommentViaWithReference).save(comment2)

        refreshed_post = test_domain.get_dao(PostViaWithReference).get(post.id)
        with mock.patch(
            "protean.core.field.association.HasMany._fetch_objects"
        ) as mock_fetch_objects:
            for _ in range(3):
                getattr(refreshed_post, "comments")
        assert mock_fetch_objects.call_count == 0

    def test_that_entities_up_to_configured_limit_value_are_retrieved(
        self, test_domain, persisted_post
    ):
        for i in range(1, 13):
            comment = Comment(
                content=f"Comment {i}", post_id=persisted_post.id
            )  # FIXME This should not be necessary
            test_domain.get_dao(Comment).save(comment)
            persisted_post.add_comments(comment)
            test_domain.get_dao(Post).save(persisted_post)

        updated_post = test_domain.get_dao(Post).get(persisted_post.id)
        assert len(updated_post.comments) == 12
