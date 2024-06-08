"""This test file is a mirror image of `test_aggregate_association.py` but testing with DAOs.

Accessing DAOs and persisting via them is not ideal. This test file is here only to highlight
breakages at the DAO level."""

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
        test_domain.register(Author, part_of=Account)
        test_domain.register(Post)
        test_domain.register(Profile, part_of=Account)

    def test_successful_initialization_of_entity_with_has_one_association(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)
        author = Author(first_name="John", last_name="Doe", account=account)
        test_domain.repository_for(Author)._dao.save(author)

        assert all(key in author.__dict__ for key in ["account", "account_email"])
        assert author.account.email == account.email
        assert author.account_email == account.email

        refreshed_account = test_domain.repository_for(Account)._dao.get(account.email)
        assert refreshed_account.author.id == author.id
        assert refreshed_account.author == author


class TestHasMany:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Post)
        test_domain.register(Comment, part_of=Post)

    @pytest.fixture
    def persisted_post(self, test_domain):
        post = test_domain.repository_for(Post)._dao.create(content="Do Re Mi Fa")
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


class TestReference:
    def test_that_reference_field_attribute_name_is_set_properly(self):
        assert attributes(Author)["account_email"].attribute_name is not None
