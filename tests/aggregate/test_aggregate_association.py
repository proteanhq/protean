import mock
import pytest

from protean.reflection import attributes

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
        test_domain.register(Comment)
        test_domain.register(Author)
        test_domain.register(AccountVia)
        test_domain.register(AccountViaWithReference)
        test_domain.register(Post)
        test_domain.register(Profile)
        test_domain.register(ProfileVia)
        test_domain.register(ProfileViaWithReference)
        test_domain.init(traverse=False)

    def test_successful_initialization_of_entity_with_has_one_association(
        self, test_domain
    ):
        account = Account(
            email="john.doe@gmail.com",
            password="a1b2c3",
            author=Author(first_name="John", last_name="Doe"),
        )
        test_domain.repository_for(Account).add(account)

        updated_account = test_domain.repository_for(Account).get(account.email)
        updated_author = updated_account.author

        updated_author.account  # To refresh and load the account  # FIXME Auto-load child entities
        assert all(
            key in updated_author.__dict__ for key in ["account", "account_email"]
        )
        assert updated_author.account.email == account.email
        assert updated_author.account_email == account.email

        assert updated_account.author.id == updated_author.id
        assert updated_account.author == updated_author

    def test_successful_has_one_initialization_with_a_class_containing_via_and_reference(
        self, test_domain
    ):
        account = AccountViaWithReference(
            email="john.doe@gmail.com",
            password="a1b2c3",
            username="johndoe",
        )
        profile = ProfileViaWithReference(about_me="Lorem Ipsum", ac=account)
        account.profile = profile
        test_domain.repository_for(AccountViaWithReference).add(account)

        refreshed_account = test_domain.repository_for(AccountViaWithReference).get(
            account.email
        )
        assert refreshed_account.profile == profile

    @mock.patch("protean.fields.association.Association._fetch_objects")
    def test_that_subsequent_access_after_first_retrieval_do_not_fetch_record_again(
        self, mock, test_domain
    ):
        account = AccountViaWithReference(
            email="john.doe@gmail.com", password="a1b2c3", username="johndoe"
        )
        profile = ProfileViaWithReference(about_me="Lorem Ipsum", ac=account)
        account.profile = profile
        test_domain.repository_for(AccountViaWithReference).add(account)

        mock.return_value = profile

        refreshed_account = test_domain.repository_for(AccountViaWithReference).get(
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
        test_domain.register(Account)
        test_domain.register(Author)
        test_domain.register(Post)
        test_domain.register(PostVia)
        test_domain.register(PostViaWithReference)
        test_domain.register(Comment)
        test_domain.register(CommentVia)
        test_domain.register(CommentViaWithReference)
        test_domain.init(traverse=False)

    @pytest.fixture
    def persisted_post(self, test_domain):
        post = test_domain.repository_for(Post).add(Post(content="Do Re Mi Fa"))
        return post

    def test_successful_initialization_of_entity_with_has_many_association(
        self, test_domain
    ):
        post = Post(
            content="Lorem Ipsum",
            comments=[
                Comment(id=101, content="First Comment"),
                Comment(id=102, content="Second Comment"),
            ],
        )
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

    def test_adding_multiple_associations_at_the_same_time_before_aggregate_save(
        self, test_domain
    ):
        post = Post(content="Lorem Ipsum")
        post.add_comments(
            [
                Comment(id=101, content="First Comment"),
                Comment(id=102, content="Second Comment"),
            ],
        )
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
        # Save the aggregate first, which is what happens in reality
        test_domain.repository_for(Post).add(post)

        comment1 = Comment(id=101, content="First Comment")
        comment2 = Comment(id=102, content="Second Comment")

        # Comments follow later
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
        post = PostVia(
            content="Lorem Ipsum",
            comments=[
                CommentVia(id=101, content="First Comment"),
                CommentVia(id=102, content="Second Comment"),
            ],
        )
        test_domain.repository_for(PostVia).add(post)

        refreshed_post = test_domain.repository_for(PostVia)._dao.get(post.id)
        assert len(refreshed_post.comments) == 2
        assert "comments" in refreshed_post.__dict__  # Available after access

        assert isinstance(refreshed_post.comments, list)
        assert all(
            comment.id in [101, 102] for comment in refreshed_post.comments
        )  # `__iter__` magic here
        for comment in refreshed_post.comments:
            assert comment.posting_id == post.id

    def test_successful_has_one_initialization_with_a_class_containing_via_and_reference(
        self, test_domain
    ):
        post = PostViaWithReference(
            content="Lorem Ipsum",
            comments=[
                CommentViaWithReference(id=101, content="First Comment"),
                CommentViaWithReference(id=102, content="First Comment"),
            ],
        )
        test_domain.repository_for(PostViaWithReference).add(post)

        refreshed_post = test_domain.repository_for(PostViaWithReference)._dao.get(
            post.id
        )
        assert len(refreshed_post.comments) == 2
        assert "comments" in refreshed_post.__dict__  # Available after access

        assert isinstance(refreshed_post.comments, list)
        assert all(
            comment.id in [101, 102] for comment in refreshed_post.comments
        )  # `__iter__` magic here

    def test_that_subsequent_access_after_first_retrieval_do_not_fetch_record_again(
        self, test_domain
    ):
        post = PostViaWithReference(
            content="Lorem Ipsum",
            comments=[
                CommentViaWithReference(id=101, content="First Comment"),
                CommentViaWithReference(id=102, content="First Comment"),
            ],
        )
        test_domain.repository_for(PostViaWithReference).add(post)

        refreshed_post = test_domain.repository_for(PostViaWithReference)._dao.get(
            post.id
        )
        with mock.patch("protean.fields.HasMany._fetch_objects") as mock_fetch_objects:
            for _ in range(3):
                getattr(refreshed_post, "comments")
        assert mock_fetch_objects.call_count == 0


class TestReference:
    def test_that_reference_field_attribute_name_is_set_properly(self):
        assert attributes(Author)["account_email"].attribute_name is not None
