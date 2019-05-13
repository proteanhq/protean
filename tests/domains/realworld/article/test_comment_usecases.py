"""Test Comment Use Cases"""
from protean.core.tasklet import Tasklet

from tests.support.domains.realworld.article.domain.model.article import Article, Comment
from tests.support.domains.realworld.article.application.comments import AddCommentRequestObject
from tests.support.domains.realworld.article.application.comments import AddCommentUseCase
from tests.support.domains.realworld.article.application.comments import GetCommentsRequestObject
from tests.support.domains.realworld.article.application.comments import GetCommentsUseCase
from tests.support.domains.realworld.article.application.comments import DeleteCommentRequestObject
from tests.support.domains.realworld.article.application.comments import DeleteCommentUseCase
from tests.support.domains.realworld.profile.domain.model.user import User, Email


class TestAddComment:
    """Test Add Comment UseCase"""

    def test_success(self):
        """Test Successful Comment Addition"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)

        payload = {'token': user.token, 'slug': article.slug, 'body': 'It takes a Jacobian'}
        response = Tasklet.perform(Article, AddCommentUseCase, AddCommentRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert isinstance(response.value, Comment)
        assert response.value.id in [comment.id for comment in article.comments]

    def test_failure(self):
        """Test Failure in profile follow"""

        user = User.create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
            bio='I work at Webmart', image='https://234ssll.xfg')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)

        payload = {'token': user.token, 'slug': article.slug}
        response = Tasklet.perform(Article, AddCommentUseCase, AddCommentRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 422
        assert article.comments is None


class TestGetComments:
    """Test Retrieval of an article's comments"""

    def test_success(self):
        """Test that articles can be listed"""

        user = User.create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
            bio='I work at Webmart', image='https://234ssll.xfg')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)
        Comment.create(body='Really!?', user=user, article=article)
        Comment.create(body='No, it doesn\'t!', user=user, article=article)

        payload = {'slug': article.slug}
        response = Tasklet.perform(Comment, GetCommentsUseCase, GetCommentsRequestObject,
                                   payload=payload)

        assert response is not None
        assert response.is_successful
        assert response.value.offset == 0
        assert response.value.total == 2
        assert response.value.first.body == 'Really!?'

    def test_paginated(self):
        """Test that articles can be paginated"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)
        Comment.create(body='Really!?', user=user, article=article)
        Comment.create(body='No, it doesn\'t!', user=user, article=article)
        Comment.create(body='For sure, it does!', user=user, article=article)
        Comment.create(body='And how would YOU know?', user=user, article=article)

        payload = {'slug': article.slug, 'page': 2, 'per_page': 2}
        response = Tasklet.perform(Comment, GetCommentsUseCase, GetCommentsRequestObject,
                                   payload=payload)

        assert response is not None
        assert response.is_successful
        assert response.value.offset == 2
        assert response.value.total == 4
        assert response.value.first.body == 'For sure, it does!'

    def test_no_results(self):
        """Test that no articles are returned when there are none"""
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)
        payload = {'slug': article.slug}
        response = Tasklet.perform(Comment, GetCommentsUseCase, GetCommentsRequestObject,
                                   payload=payload)

        assert response is not None
        assert response.is_successful
        assert response.value.offset == 0
        assert response.value.total == 0
        assert response.value.items == []


class TestDeleteComment:
    """Test Delete Comment Use Case"""
    # FIXME Test that Comments exist before attempting delete
    # FIXME Test that only the user who created the comment can delete them

    def test_success(self):
        """Test Successful Comment Deletion"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)

        payload = {'token': user.token, 'slug': article.slug, 'body': 'It takes a Jacobian'}
        response = Tasklet.perform(Article, AddCommentUseCase, AddCommentRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert isinstance(response.value, Comment)
        assert response.value.id in [comment.id for comment in article.comments]

        payload = {'token': user.token, 'slug': article.slug, 'comment_id': response.value.id}
        response = Tasklet.perform(Article, DeleteCommentUseCase, DeleteCommentRequestObject,
                                   payload=payload)
        refreshed_article = Article.get(article.id)
        assert refreshed_article.comments is None

    def test_failure(self):
        """Test Failure in profile follow"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)

        payload = {'token': user.token, 'slug': article.slug, 'body': 'It takes a Jacobian'}
        response = Tasklet.perform(Article, AddCommentUseCase, AddCommentRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert isinstance(response.value, Comment)
        assert response.value.id in [comment.id for comment in article.comments]

        payload = {'token': user.token, 'slug': article.slug, 'comment_id': 342234}
        response = Tasklet.perform(Article, DeleteCommentUseCase, DeleteCommentRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 404

        refreshed_article = Article.get(article.id)
        assert refreshed_article.comments is not None

        payload = {'token': user.token, 'slug': article.slug}
        response = Tasklet.perform(Article, DeleteCommentUseCase, DeleteCommentRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 422

        refreshed_article = Article.get(article.id)
        assert refreshed_article.comments is not None
