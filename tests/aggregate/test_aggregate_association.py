import pytest

from protean.reflection import attributes

from .elements import (
    Account,
    Author,
    Comment,
    Post,
    Profile,
)


class TestHasOne:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(Post)
        test_domain.register(Comment, part_of=Post)
        test_domain.register(Author, part_of=Account)
        test_domain.register(Profile, part_of=Account)
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


class TestHasMany:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(Author, part_of=Account)
        test_domain.register(Post)
        test_domain.register(Comment, part_of=Post)
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


class TestReference:
    def test_that_reference_field_attribute_name_is_set_properly(self):
        assert attributes(Author)["account_email"].attribute_name is not None
