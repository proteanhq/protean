"""Tests for Entities under Articles Aggregate"""
import pytest

from protean.core.exceptions import ValidationError
from tests.old.support.domains.realworld.article.domain.model.article import Article, Comment
from tests.old.support.domains.realworld.profile.domain.model.user import User, Email


class TestArticle:
    """Tests for Article Aggregate"""

    def test_init(self, test_domain):
        """Test initialization of Article Entity"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')
        article = test_domain.get_repository(Article).create(
            slug='how-to-train-your-dragon',
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user,
            tagList=['dragons', 'training'])
        assert article is not None
        assert article.id is not None
        assert article.title == 'How to train your dragon'
        assert article.description == 'Ever wonder how?'
        assert article.body == 'It takes a Jacobian'
        assert article.author == user
        assert article.tagList == ['dragons', 'training']

        with pytest.raises(ValidationError):
            article = Article(description='How to train your dragon')

        required_fields = [field_name for field_name in Article.meta_.declared_fields
                           if Article.meta_.declared_fields[field_name].required]
        assert all(
            field in required_fields for field in [
                'title', 'created_at',
                'updated_at', 'author'])


class TestComment:
    """Tests for Comment Entity"""

    def test_init(self, test_domain):
        """Test initialization of Comment Entity"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')
        article = test_domain.get_repository(Article).create(
            slug='how-to-train-your-dragon', title='How to train your dragon',
            description='Ever wonder how?', body='It takes a Jacobian', author=user)

        # FIXME This is a much more elegant method of handling entities under aggregates
        # comment = article.comments.add(body='It takes a Jacobian')
        comment = test_domain.get_repository(Comment).create(user=user, article=article, body='It takes a Jacobian')
        assert comment is not None
        assert comment.id is not None
        assert comment.body == 'It takes a Jacobian'

        required_fields = [field_name for field_name in Comment.meta_.declared_fields
                           if Comment.meta_.declared_fields[field_name].required]
        assert len(required_fields) == 5
        assert all(
            field in required_fields for field in [
                'body', 'user', 'created_at',
                'updated_at', 'article'])
