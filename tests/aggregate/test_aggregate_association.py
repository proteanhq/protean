# Protean
import mock
import pytest

from protean.core.queryset import QuerySet
from protean.core.repository.resultset import ResultSet

# Local/Relative Imports
from .elements import (Account, AccountVia, AccountViaWithReference, Author, Comment,
                       CommentVia, CommentViaWithReference, Post, PostVia,
                       PostViaWithReference, Profile, ProfileVia, ProfileViaWithReference)


class TestHasOne:

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(Author)
        test_domain.register(AccountVia)
        test_domain.register(AccountViaWithReference)
        test_domain.register(Profile)
        test_domain.register(ProfileVia)
        test_domain.register(ProfileViaWithReference)

    def test_successful_initialization_of_entity_with_has_one_association(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)
        author = Author(first_name='John', last_name='Doe', account=account)
        test_domain.get_dao(Author).save(author)

        assert all(key in author.__dict__ for key in ['account', 'account_email'])
        assert author.account.email == account.email
        assert author.account_email == account.email

        assert account.author.id == author.id
        assert account.author == author

    def test_successful_has_one_intiliazation_with_a_class_containing_via_and_no_reference(self, test_domain):
        account = AccountVia(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(AccountVia).save(account)
        profile = ProfileVia(profile_id='12345', about_me='Lorem Ipsum', account_email=account.email)
        test_domain.get_dao(ProfileVia).save(profile)

        assert account.profile == profile

    def test_successful_has_one_intiliazation_with_a_class_containing_via_and_reference(self, test_domain):
        account = AccountViaWithReference(email='john.doe@gmail.com', password='a1b2c3', username='johndoe')
        test_domain.get_dao(AccountViaWithReference).save(account)
        profile = ProfileViaWithReference(about_me='Lorem Ipsum', ac=account)
        test_domain.get_dao(ProfileViaWithReference).save(profile)

        assert account.profile == profile

    @mock.patch('protean.core.repository.dao.BaseDAO.find_by')
    def test_that_subsequent_access_after_first_retrieval_do_not_fetch_record_again(self, find_by_mock, test_domain):
        account = AccountViaWithReference(email='john.doe@gmail.com', password='a1b2c3', username='johndoe')
        test_domain.get_dao(AccountViaWithReference).save(account)
        profile = ProfileViaWithReference(about_me='Lorem Ipsum', ac=account)
        test_domain.get_dao(ProfileViaWithReference).save(profile)

        for _ in range(3):
            getattr(account, 'profile')
        assert find_by_mock.call_count == 1


class TestHasMany:

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Post)
        test_domain.register(PostVia)
        test_domain.register(PostViaWithReference)
        test_domain.register(Comment)
        test_domain.register(CommentVia)
        test_domain.register(CommentViaWithReference)

    def test_successful_initialization_of_entity_with_has_many_association(self, test_domain):
        post = Post(content='Lorem Ipsum')
        test_domain.get_dao(Post).save(post)
        comment1 = Comment(id=101, content='First Comment', post=post)
        comment2 = Comment(id=102, content='Second Comment', post=post)
        test_domain.get_dao(Comment).save(comment1)
        test_domain.get_dao(Comment).save(comment2)

        assert comment1.post.id == post.id
        assert comment2.post.id == post.id
        assert 'comments' not in post.__dict__
        assert len(post.comments) == 2
        assert 'comments' in post.__dict__  # Avaiable after access

        assert isinstance(post.comments, QuerySet)
        assert isinstance(post.comments.all(), ResultSet)
        assert all(comment.id in [101, 102] for comment in post.comments)  # `__iter__` magic here

    def test_successful_has_one_intiliazation_with_a_class_containing_via_and_no_reference(self, test_domain):
        post = PostVia(content='Lorem Ipsum')
        test_domain.get_dao(PostVia).save(post)
        comment1 = CommentVia(id=101, content='First Comment', posting_id=post.id)
        comment2 = CommentVia(id=102, content='First Comment', posting_id=post.id)
        test_domain.get_dao(CommentVia).save(comment1)
        test_domain.get_dao(CommentVia).save(comment2)

        assert comment1.posting_id == post.id
        assert comment2.posting_id == post.id
        assert 'comments' not in post.__dict__
        assert len(post.comments) == 2
        assert 'comments' in post.__dict__  # Avaiable after access

        assert isinstance(post.comments, QuerySet)
        assert isinstance(post.comments.all(), ResultSet)
        assert all(comment.id in [101, 102] for comment in post.comments)  # `__iter__` magic here

    def test_successful_has_one_intiliazation_with_a_class_containing_via_and_reference(self, test_domain):
        post = PostViaWithReference(content='Lorem Ipsum')
        test_domain.get_dao(PostViaWithReference).save(post)
        comment1 = CommentViaWithReference(id=101, content='First Comment', posting=post)
        comment2 = CommentViaWithReference(id=102, content='First Comment', posting=post)
        test_domain.get_dao(CommentViaWithReference).save(comment1)
        test_domain.get_dao(CommentViaWithReference).save(comment2)

        assert comment1.posting_id == post.id
        assert comment2.posting_id == post.id
        assert 'comments' not in post.__dict__
        assert len(post.comments) == 2
        assert 'comments' in post.__dict__  # Avaiable after access

        assert isinstance(post.comments, QuerySet)
        assert isinstance(post.comments.all(), ResultSet)
        assert all(comment.id in [101, 102] for comment in post.comments)  # `__iter__` magic here

    @mock.patch('protean.core.queryset.QuerySet.filter')
    @mock.patch('protean.core.repository.dao.BaseDAO.exists')
    def test_that_subsequent_access_after_first_retrieval_do_not_fetch_record_again(self, exists_mock,
                                                                                    filter_mock, test_domain):
        exists_mock.return_value = False
        post = PostViaWithReference(content='Lorem Ipsum')
        test_domain.get_dao(PostViaWithReference).save(post)
        comment1 = CommentViaWithReference(id=101, content='First Comment', posting=post)
        comment2 = CommentViaWithReference(id=102, content='First Comment', posting=post)
        test_domain.get_dao(CommentViaWithReference).save(comment1)
        test_domain.get_dao(CommentViaWithReference).save(comment2)

        for _ in range(3):
            getattr(post, 'comments')
        assert filter_mock.call_count == 1
