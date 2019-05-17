"""Use Cases for Article Functionality"""

from protean import Domain
from protean.conf import active_config
from protean.core.entity import BaseEntity
from protean.core.exceptions import ObjectNotFoundError
from protean.core.transport import InvalidRequestObject
from protean.core.transport import ResponseFailure
from protean.core.transport import ResponseSuccess
from protean.core.transport import Status
from protean.core.transport import RequestObjectFactory
from protean.core.usecase.base import UseCase
from protean.domain import RequestObject

from tests.support.domains.realworld.profile.domain.model.user import User, Favorite


@RequestObject
class ListArticlesRequestObject:
    """
    This class encapsulates the Request Object for Listing Articles
    """

    def __init__(self, entity_cls, offset=0, limit=None, order_by=(),
                 filters=None):
        """Initialize Request Object with parameters"""
        self.entity_cls = entity_cls
        self.offset = offset
        self.limit = limit or active_config.PER_PAGE
        self.order_by = order_by
        self.filters = filters if filters else {}

    @classmethod  # noqa: C901
    def from_dict(cls, adict):
        """Initialize a ListRequestObject object from a dictionary."""
        invalid_req = InvalidRequestObject()

        if 'entity_cls' not in adict:
            invalid_req.add_error('entity_cls', 'is required')
        else:
            entity_cls = adict['entity_cls']

        # Extract the pagination parameters from the input
        offset = int(adict.pop('offset', 0))
        limit = int(adict.pop('limit', getattr(active_config, 'PER_PAGE', 10)))
        order_by = adict.pop('order_by', ('-created_at'))

        # Check for invalid request conditions
        if offset < 0:
            invalid_req.add_error('offset', 'is invalid')

        filters = {}

        tag = adict.pop('tag', None)
        if tag:
            filters['tagList__contains'] = tag

        author_username = adict.pop('author', None)
        if author_username:
            try:
                author = Domain().get_repository(User).find_by(username=author_username)
            except ObjectNotFoundError:
                invalid_req.add_error('author', 'is invalid')

            filters['author_id'] = author.id

        favorited = adict.pop('favorited', None)
        if favorited:
            try:
                user = Domain().get_repository(User).find_by(username=favorited)
            except ObjectNotFoundError:
                invalid_req.add_error('favorited', 'is invalid')

            favorites = Domain().get_repository(Favorite).query.filter(user_id=user.id).all()
            article_ids = [favorite.article_id for favorite in favorites]

            filters['id__in'] = article_ids

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity_cls, offset, limit, order_by, filters)


class ListArticlesUseCase(UseCase):
    """
    This class implements the usecase for listing all resources
    """

    def process_request(self, request_object):
        """Return a list of resources"""
        repo = Domain().get_repository(request_object.entity_cls)
        resources = (repo.query
                     .filter(**request_object.filters)
                     .offset(request_object.offset)
                     .limit(request_object.limit)
                     .order_by(request_object.order_by)
                     .all())
        return ResponseSuccess(Status.SUCCESS, resources)


@RequestObject
class FeedArticlesRequestObject:
    """
    This class encapsulates the Request Object for Listing Articles
    """

    def __init__(self, entity_cls, token, offset=0, limit=None, order_by=(),
                 filters=None):
        """Initialize Request Object with parameters"""
        self.entity_cls = entity_cls
        self.offset = offset
        self.limit = limit or active_config.PER_PAGE
        self.order_by = order_by
        self.filters = filters if filters else {}

    @classmethod
    def from_dict(cls, adict):
        """Initialize a ListRequestObject object from a dictionary."""
        invalid_req = InvalidRequestObject()

        if 'entity_cls' not in adict:
            invalid_req.add_error('entity_cls', 'is required')
        else:
            entity_cls = adict['entity_cls']

        # Extract the pagination parameters from the input
        offset = int(adict.pop('offset', 0))
        limit = int(adict.pop('limit', getattr(active_config, 'PER_PAGE', 10)))
        order_by = adict.pop('order_by', ('-created_at'))

        # Check for invalid request conditions
        if offset < 0:
            invalid_req.add_error('offset', 'is invalid')

        if 'token' not in adict:
            invalid_req.add_error('token', 'is required')
        else:
            token = adict['token']

        filters = {}
        try:
            user = Domain().get_repository(User).find_by(token=token)
        except ObjectNotFoundError:
            invalid_req.add_error('token', 'is invalid')

        if user.follows:
            follower_ids = [follower.user_id for follower in user.follows]
        else:
            follower_ids = []
        filters['author_id__in'] = follower_ids

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity_cls, token, offset, limit, order_by, filters)


GetArticleRequestObject = RequestObjectFactory.construct(
    'GetArticleRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('slug', str, {'required': True})])


class GetArticleUseCase(UseCase):
    """Fetch Profile by Slug"""

    def process_request(self, request_object):
        """Process Fetch Article by Slug"""
        try:
            repo = Domain().get_repository(request_object.entity_cls)
            article = repo.find_by(slug=request_object.slug)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'slug': 'Article not found'})

        return ResponseSuccess(Status.SUCCESS, article)


CreateArticleRequestObject = RequestObjectFactory.construct(
    'CreateArticleRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('title', str, {'required': True}),
     ('description', str, {'required': True}),
     ('body', str),
     ('author', BaseEntity, {'required': True})
     ])


class CreateArticleUseCase(UseCase):
    """Create a new Article"""

    def process_request(self, request_object):
        """Process Article Creation"""
        repo = Domain().get_repository(request_object.entity_cls)
        author = repo.create(
            title=request_object.title,
            description=request_object.description,
            body=request_object.body,
            author=request_object.author)

        return ResponseSuccess(Status.SUCCESS_CREATED, author)


UpdateArticleRequestObject = RequestObjectFactory.construct(
    'UpdateArticleRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('slug', str, {'required': True}),
     ('data', dict, {'required': True})])


class UpdateArticleUseCase(UseCase):
    """Update details for an existing article"""

    def process_request(self, request_object):
        """Process Article Update Request"""
        repo = Domain().get_repository(request_object.entity_cls)

        try:
            article = repo.find_by(slug=request_object.slug)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'slug': 'Article does not exist'})

        if 'title' in request_object.data:
            article.title = request_object.data['title']
        if 'description' in request_object.data:
            article.description = request_object.data['description']
        if 'body' in request_object.data:
            article.body = request_object.data['body']
        if 'author' in request_object.data:
            article.author = request_object.data['author']
        repo.save(article)

        return ResponseSuccess(Status.SUCCESS, article)


DeleteArticleRequestObject = GetArticleRequestObject


class DeleteArticleUseCase(UseCase):
    """Delete Article by Slug"""

    def process_request(self, request_object):
        """Delete Article by Slug"""
        try:
            repo = Domain().get_repository(request_object.entity_cls)
            article = repo.find_by(slug=request_object.slug)
            article.delete()
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'slug': 'Article not found'})

        return ResponseSuccess(Status.SUCCESS_WITH_NO_CONTENT, article)


FavoriteArticleRequestObject = RequestObjectFactory.construct(
    'FavoriteArticleRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('slug', str, {'required': True}),
     ('token', str, {'required': True})])


class FavoriteArticleUseCase(UseCase):
    """Unfavorite Article by Slug"""

    def process_request(self, request_object):
        """Process request for favoriting Article by slug"""
        try:
            logged_in_user = Domain().get_repository(User).find_by(token=request_object.token)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'token': 'Token is invalid'})

        try:
            repo = Domain().get_repository(request_object.entity_cls)
            article = repo.find_by(slug=request_object.slug)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'slug': 'Article Slug is invalid'})

        logged_in_user.favorite(article)
        return ResponseSuccess(Status.SUCCESS, article)


class UnfavoriteArticleUseCase(UseCase):
    """Unfollow Profile by Username"""

    def process_request(self, request_object):
        """Process request for following profile by username"""
        try:
            logged_in_user = Domain().get_repository(User).find_by(token=request_object.token)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'token': 'Token is invalid'})

        try:
            repo = Domain().get_repository(request_object.entity_cls)
            article = repo.find_by(slug=request_object.slug)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'slug': 'Article Slug is invalid'})

        logged_in_user.unfavorite(article)
        return ResponseSuccess(Status.SUCCESS, article)


GetTagsRequestObject = RequestObjectFactory.construct(
    'GetTagsRequestObject',
    [('entity_cls', BaseEntity, {'required': True})])


class GetTagsUseCase(UseCase):
    """Fetch all tags"""

    def process_request(self, request_object):
        """Process Fetch all tags"""
        # FIXME Correct Usage: tags = request_object.entity_cls.query.distinct('tagList')
        repo = Domain().get_repository(request_object.entity_cls)
        resultset = repo.query.all()
        if resultset.items:
            tagsList = [article.tagList for article in resultset.items
                        if article.tagList is not None]
            tags = [item for sublist in tagsList for item in sublist]
            tags = list(set(tags))

        return ResponseSuccess(Status.SUCCESS, tags or [])
