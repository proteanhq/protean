"""Test Article UseCases"""
import datetime

from protean.core.tasklet import Tasklet

from tests.support.domains.realworld.article.domain.model.article import Article
from tests.support.domains.realworld.article.application.articles import CreateArticleRequestObject
from tests.support.domains.realworld.article.application.articles import CreateArticleUseCase
from tests.support.domains.realworld.article.application.articles import FavoriteArticleRequestObject
from tests.support.domains.realworld.article.application.articles import FavoriteArticleUseCase
from tests.support.domains.realworld.article.application.articles import FeedArticlesRequestObject
from tests.support.domains.realworld.article.application.articles import GetArticleRequestObject
from tests.support.domains.realworld.article.application.articles import GetArticleUseCase
from tests.support.domains.realworld.article.application.articles import GetTagsRequestObject
from tests.support.domains.realworld.article.application.articles import GetTagsUseCase
from tests.support.domains.realworld.article.application.articles import ListArticlesRequestObject
from tests.support.domains.realworld.article.application.articles import ListArticlesUseCase
from tests.support.domains.realworld.article.application.articles import UnfavoriteArticleUseCase
from tests.support.domains.realworld.article.application.articles import UpdateArticleRequestObject
from tests.support.domains.realworld.article.application.articles import UpdateArticleUseCase
from tests.support.domains.realworld.profile.domain.model.user import User, Email


class TestListArticles:
    """Test Listing of Articles"""

    def test_success(self):
        """Test that articles can be listed"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        Article.create(title='How to train your dragon', description='Ever wonder how?',
                       body='It takes a Jacobian', author=user)
        Article.create(title='How to train your dragon 2', description='So toothless',
                       body='It a dragon', author=user)

        response = Tasklet.perform(Article, ListArticlesUseCase, ListArticlesRequestObject,
                                   payload={})

        assert response is not None
        assert response.is_successful
        assert response.value.offset == 0
        assert response.value.total == 2
        assert response.value.first.title == 'How to train your dragon'

    def test_paginated(self):
        """Test that articles can be paginated"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        Article.create(title='How to train your dragon', description='Ever wonder how?',
                       body='It takes a Jacobian', author=user)
        Article.create(title='How to train your dragon 2', description='So toothless',
                       body='It a dragon', author=user)
        Article.create(title='GOT 1', description='Oh man, this is unwatchable!',
                       body='What does everybody see in this?', author=user)
        Article.create(title='GOT 2', description='I am hooked!',
                       body='Where was this for so long?', author=user)

        response = Tasklet.perform(Article, ListArticlesUseCase, ListArticlesRequestObject,
                                   payload=dict(offset=2, limit=2))

        assert response is not None
        assert response.is_successful
        assert response.value.offset == 2
        assert response.value.total == 4
        assert response.value.first.title == 'GOT 1'

    def test_no_results(self):
        """Test that no articles are returned when there are none"""
        response = Tasklet.perform(Article, ListArticlesUseCase, ListArticlesRequestObject,
                                   payload={})

        assert response is not None
        assert response.is_successful
        assert response.value.offset == 0
        assert response.value.total == 0
        assert response.value.items == []

    def test_filter_by_tag(self):
        """Test Filtering by specific tag"""
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        Article.create(title='How to train your dragon', description='Ever wonder how?',
                       body='It takes a Jacobian', author=user, tagList=['dragons', 'training'],
                       created_at=(datetime.datetime.now() - datetime.timedelta(days=3)))
        Article.create(title='How to train your dragon 2', description='So toothless',
                       body='It a dragon', author=user, tagList=['reactjs', 'angularjs', 'dragons'],
                       created_at=(datetime.datetime.now() - datetime.timedelta(days=2)))
        Article.create(title='GOT 1', description='Oh man, this is unwatchable!',
                       body='What does everybody see in this?', author=user, tagList=['GOT'],
                       created_at=(datetime.datetime.now() - datetime.timedelta(days=1)))
        Article.create(title='GOT 2', description='I am hooked!',
                       body='Where was this for so long?', author=user, tagList=['GOT', 'dragons'])

        response = Tasklet.perform(Article, ListArticlesUseCase, ListArticlesRequestObject,
                                   payload=dict(tag='dragons'))

        assert response is not None
        assert response.is_successful
        assert response.value.total == 3
        assert response.value.first.title == 'GOT 2'

    def test_filter_by_non_existant_tag(self):
        """Test Filtering by a non-existant tag"""
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret',
                           bio='I work at Webmart', image='https://234ssll.xfg')
        Article.create(title='How to train your dragon', description='Ever wonder how?',
                       body='It takes a Jacobian', author=user, tagList=['dragons', 'training'],
                       created_at=(datetime.datetime.now() - datetime.timedelta(days=3)))
        Article.create(title='How to train your dragon 2', description='So toothless',
                       body='It a dragon', author=user, tagList=['reactjs', 'angularjs', 'dragons'],
                       created_at=(datetime.datetime.now() - datetime.timedelta(days=2)))
        Article.create(title='GOT 1', description='Oh man, this is unwatchable!',
                       body='What does everybody see in this?', author=user, tagList=['GOT'],
                       created_at=(datetime.datetime.now() - datetime.timedelta(days=1)))
        Article.create(title='GOT 2', description='I am hooked!',
                       body='Where was this for so long?', author=user, tagList=['GOT', 'dragons'])

        response = Tasklet.perform(Article, ListArticlesUseCase, ListArticlesRequestObject,
                                   payload=dict(tag='foobar'))

        assert response is not None
        assert response.is_successful
        assert response.value.total == 0

    def test_filter_by_author(self):
        """Test Filtering by a specific article author"""
        user1 = User.create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1',
            bio='I work at Webmart', image='https://234ssll.xfg')
        user2 = User.create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2',
            bio='I work at Weirdart', image='https://234ssdaf.xfg')
        Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user1, tagList=['dragons', 'training'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=3)))
        Article.create(
            title='How to train your dragon 2', description='So toothless',
            body='It a dragon', author=user1, tagList=['reactjs', 'angularjs', 'dragons'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=2)))
        Article.create(
            title='GOT 1', description='Oh man, this is unwatchable!',
            body='What does everybody see in this?', author=user2, tagList=['GOT'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=1)))
        Article.create(
            title='GOT 2', description='I am hooked!',
            body='Where was this for so long?', author=user2, tagList=['GOT', 'dragons'])

        response = Tasklet.perform(Article, ListArticlesUseCase, ListArticlesRequestObject,
                                   payload=dict(author='janedoe'))

        assert response is not None
        assert response.is_successful
        assert response.value.total == 2
        assert response.value.first.title == 'GOT 2'

    def test_filter_by_favorited(self):
        """Test Filtering by a specific article author"""
        user1 = User.create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1',
            bio='I work at Webmart', image='https://234ssll.xfg')
        user2 = User.create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2',
            bio='I work at Weirdart', image='https://234ssdaf.xfg')
        Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user1, tagList=['dragons', 'training'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=3)))
        article2 = Article.create(
            title='How to train your dragon 2', description='So toothless',
            body='It a dragon', author=user1, tagList=['reactjs', 'angularjs', 'dragons'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=2)))
        article3 = Article.create(
            title='GOT 1', description='Oh man, this is unwatchable!',
            body='What does everybody see in this?', author=user2, tagList=['GOT'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=1)))
        article4 = Article.create(
            title='GOT 2', description='I am hooked!',
            body='Where was this for so long?', author=user2, tagList=['GOT', 'dragons'])
        user1.favorite(article2)
        user2.favorite(article2)
        user2.favorite(article3)
        user2.favorite(article4)
        response = Tasklet.perform(Article, ListArticlesUseCase, ListArticlesRequestObject,
                                   payload=dict(favorited='janedoe'))

        assert response is not None
        assert response.is_successful
        assert response.value.total == 3
        assert response.value.first.title == 'GOT 2'


class TestFeedArticles:
    """Test Feeding of Articles"""

    def test_success(self):
        """Test that articles of followed users can be listed"""

        user1 = User.create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1',
            bio='I work at Webmart', image='https://234ssll.xfg')
        user2 = User.create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2',
            bio='I work at Weirdart', image='https://234ssdaf.xfg')
        user3 = User.create(
            email=Email.build(address='puppy.doe@gmail.com'), username='puppydoe', password='secret3',
            bio='I don\' work at all', image='https://23ws344.xfg')
        Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user1, tagList=['dragons', 'training'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=3)))
        Article.create(
            title='How to train your dragon 2', description='So toothless',
            body='It a dragon', author=user1, tagList=['reactjs', 'angularjs', 'dragons'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=2)))
        Article.create(
            title='GOT 1', description='Oh man, this is unwatchable!',
            body='What does everybody see in this?', author=user2, tagList=['GOT'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=1)))
        Article.create(
            title='GOT 2', description='I am hooked!',
            body='Where was this for so long?', author=user2, tagList=['GOT', 'dragons'])
        Article.create(
            title='Doggone!', description='This is crazy',
            body='The first article written by a puppy', author=user3,
            tagList=['dog', 'cat'])
        user2.follow(user1)
        user2.follow(user3)
        response = Tasklet.perform(Article, ListArticlesUseCase, FeedArticlesRequestObject,
                                   payload=dict(token=user2.token))

        assert response is not None
        assert response.is_successful
        assert response.value.total == 3
        assert response.value.first.title == 'Doggone!'

    def test_paginated(self):
        """Test that articles of followed users can be listed"""

        user1 = User.create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1',
            bio='I work at Webmart', image='https://234ssll.xfg')
        user2 = User.create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2',
            bio='I work at Weirdart', image='https://234ssdaf.xfg')
        user3 = User.create(
            email=Email.build(address='puppy.doe@gmail.com'), username='puppydoe', password='secret3',
            bio='I don\' work at all', image='https://23ws344.xfg')
        Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user1, tagList=['dragons', 'training'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=3)))
        Article.create(
            title='How to train your dragon 2', description='So toothless',
            body='It a dragon', author=user1, tagList=['reactjs', 'angularjs', 'dragons'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=2)))
        Article.create(
            title='GOT 1', description='Oh man, this is unwatchable!',
            body='What does everybody see in this?', author=user2, tagList=['GOT'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=1)))
        Article.create(
            title='GOT 2', description='I am hooked!',
            body='Where was this for so long?', author=user2, tagList=['GOT', 'dragons'])
        Article.create(
            title='Doggone!', description='This is crazy',
            body='The first article written by a puppy', author=user3,
            tagList=['dog', 'cat'])

        # Follow two users
        user2.follow(user1)
        user2.follow(user3)
        response = Tasklet.perform(Article, ListArticlesUseCase, FeedArticlesRequestObject,
                                   payload=dict(token=user2.token, offset=2, limit=2))

        # The response is just one record because we have offset the resultset by 2
        # The resultset is ordered by `created_at` in the reverse
        assert response is not None
        assert response.is_successful
        assert len(response.value.items) == 1
        assert response.value.total == 3
        assert response.value.first.title == 'How to train your dragon'

    def test_no_results(self):
        """Test that articles of followed users can be listed"""

        user1 = User.create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1',
            bio='I work at Webmart', image='https://234ssll.xfg')
        user2 = User.create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2',
            bio='I work at Weirdart', image='https://234ssdaf.xfg')
        user3 = User.create(
            email=Email.build(address='puppy.doe@gmail.com'), username='puppydoe', password='secret3',
            bio='I don\' work at all', image='https://23ws344.xfg')
        Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user1, tagList=['dragons', 'training'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=3)))
        Article.create(
            title='How to train your dragon 2', description='So toothless',
            body='It a dragon', author=user1, tagList=['reactjs', 'angularjs', 'dragons'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=2)))
        Article.create(
            title='GOT 1', description='Oh man, this is unwatchable!',
            body='What does everybody see in this?', author=user2, tagList=['GOT'],
            created_at=(datetime.datetime.now() - datetime.timedelta(days=1)))
        Article.create(
            title='GOT 2', description='I am hooked!',
            body='Where was this for so long?', author=user2, tagList=['GOT', 'dragons'])
        Article.create(
            title='Doggone!', description='This is crazy',
            body='The first article written by a puppy', author=user3,
            tagList=['dog', 'cat'])

        response = Tasklet.perform(Article, ListArticlesUseCase, FeedArticlesRequestObject,
                                   payload=dict(token=user2.token, offset=2, limit=2))

        # The response is just one record because we have offset the resultset by 2
        # The resultset is ordered by `created_at` in the reverse
        assert response is not None
        assert response.is_successful
        assert len(response.value.items) == 0
        assert response.value.total == 0


class TestGetArticle:
    """Test Get Article Usecase"""

    def test_success(self):
        """Test Successful article fetch"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)

        payload = {'slug': article.slug}
        response = Tasklet.perform(Article, GetArticleUseCase, GetArticleRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert isinstance(response.value, Article)
        assert response.value.id == article.id

    def test_failure(self):
        """Test failed article fetch"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        Article.create(title='How to train your dragon', description='Ever wonder how?',
                       body='It takes a Jacobian', author=user)

        payload = {'slug': 'nonexistant'}
        response = Tasklet.perform(Article, GetArticleUseCase, GetArticleRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 404


class TestCreateArticle:
    """Test Article Creatiopn Functionality"""

    def test_success(self):
        """Test Successful Article Creation"""
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        payload = {'title': 'How to train your dragon', 'description': 'Ever wonder how?',
                   'body': 'It takes a Jacobian', 'author': user,
                   'tagList': ['dragons', 'training']}
        response = Tasklet.perform(Article, CreateArticleUseCase, CreateArticleRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert response.code.value == 201
        assert isinstance(response.value, Article)
        assert response.value.title == 'How to train your dragon'
        assert response.value.author.id == user.id

    def test_validation_failure(self):
        """Test that validation errors are thrown correctly"""
        User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        payload = {'title': 'How to train your dragon', 'description': 'Ever wonder how?',
                   'body': 'It takes a Jacobian'}
        response = Tasklet.perform(Article, CreateArticleUseCase, CreateArticleRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 422
        # FIXME Nest under `errors`
        assert response.value == {'code': 422, 'errors': [{'author': 'is required'}]}


class TestUpdateArticle:
    """Test Article Update Functionality"""

    def test_success(self):
        """Test Successful Article Registration"""
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)

        payload = {'slug': article.slug,
                   'data': {'title': 'changed.How to train your dragon'}}
        response = Tasklet.perform(Article, UpdateArticleUseCase, UpdateArticleRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert response.code.value == 200
        assert isinstance(response.value, Article)
        assert response.value.title == 'changed.How to train your dragon'

    def test_validation_failure(self):
        """Test that validation errors are thrown correctly"""
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)
        payload = {'slug': article.slug,
                   'data': {'title': None}}
        response = Tasklet.perform(Article, UpdateArticleUseCase, UpdateArticleRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 422
        # FIXME Nest under `errors`
        assert response.value == {'code': 422,
                                  'errors': [{'title': ['is required']}]}


class TestFavoriteArticle:
    """Test Favoriting an Article UseCase"""
    # FIXME Test that Article cannot be favorited again

    def test_success(self):
        """Test Successful Article Favoriting"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)
        payload = {'token': user.token, 'slug': article.slug}
        response = Tasklet.perform(Article, FavoriteArticleUseCase, FavoriteArticleRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert response.code.value == 200
        favorite_ids = [favorite.article_id for favorite in user.favorites]
        assert article.id in favorite_ids

    def test_failure(self):
        """Test Failure in profile follow"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        Article.create(title='How to train your dragon', description='Ever wonder how?',
                       body='It takes a Jacobian', author=user)

        payload = {'token': user.token}
        response = Tasklet.perform(Article, FavoriteArticleUseCase, FavoriteArticleRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 422
        assert user.favorites is None

        payload = {'token': user.token, 'slug': 'non-existant-slug'}
        response = Tasklet.perform(Article, FavoriteArticleUseCase, FavoriteArticleRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 404
        assert user.favorites is None


class TestUnfavoriteArticle:
    """Test Unfollow Profile Usecase"""
    # FIXME Test that user has already favorited article before unfavoriting

    def test_success(self):
        """Test Successful profile unfollow"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user, tagList=['dragons', 'training'])
        payload = {'token': user.token, 'slug': article.slug}
        response = Tasklet.perform(Article, FavoriteArticleUseCase, FavoriteArticleRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert response.code.value == 200
        favorite_ids = [favorite.article_id for favorite in user.favorites]
        assert article.id in favorite_ids

        response = Tasklet.perform(Article, UnfavoriteArticleUseCase, FavoriteArticleRequestObject,
                                   payload=payload)
        refreshed_user = User.get(user.id)
        assert refreshed_user.favorites is None

    def test_failure(self):
        """Test Failure in profile follow"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        article = Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)
        payload = {'token': user.token, 'slug': article.slug}
        response = Tasklet.perform(Article, FavoriteArticleUseCase, FavoriteArticleRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert response.code.value == 200
        favorite_ids = [favorite.article_id for favorite in user.favorites]
        assert article.id in favorite_ids

        payload = {'token': user.token}
        response = Tasklet.perform(User, UnfavoriteArticleUseCase, FavoriteArticleRequestObject,
                                   payload=payload)
        refreshed_user = User.get(user.id)
        assert not response.is_successful
        assert response.code.value == 422
        assert refreshed_user.favorites is not None


class TestGetTags:
    """Test Get Unique Tags from Articles"""

    def test_success(self):
        """Test Successful article fetch"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user, tagList=['dragons', 'training'])
        Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user,
            tagList=['reactjs', 'angularjs', 'dragons'])

        response = Tasklet.perform(Article, GetTagsUseCase, GetTagsRequestObject, payload={})

        assert response.is_successful
        assert isinstance(response.value, list)
        assert len(response.value) == 4
        assert all(tag in response.value for tag in
                   ['dragons', 'training', 'reactjs', 'angularjs'])

    def test_no_tags(self):
        """Test failed article fetch"""

        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        Article.create(
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)

        response = Tasklet.perform(Article, GetTagsUseCase, GetTagsRequestObject, payload={})

        assert response.is_successful
        assert response.value == []
