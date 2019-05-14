"""Use Cases for Comments Functionality"""

from protean.conf import active_config
from protean.core.entity import BaseEntity
from protean.core.exceptions import ObjectNotFoundError
from protean.core.transport import InvalidRequestObject
from protean.core.transport import ResponseFailure
from protean.core.transport import ResponseSuccess
from protean.core.transport import Status
from protean.core.transport import BaseRequestObject
from protean.core.transport import RequestObjectFactory
from protean.core.usecase import UseCase

from tests.support.domains.realworld.article.domain.model.article import Article
from tests.support.domains.realworld.profile.domain.model.user import User


AddCommentRequestObject = RequestObjectFactory.construct(
    'AddCommentRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('slug', str, {'required': True}),
     ('body', str, {'required': True}),
     ('token', str, {'required': True})])


class AddCommentUseCase(UseCase):
    """Add a comment to an article"""

    def process_request(self, request_object):
        """Process request for adding comment to an article"""
        try:
            logged_in_user = User.find_by(token=request_object.token)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'token': 'Token is invalid'})

        try:
            article = request_object.entity_cls.find_by(slug=request_object.slug)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'slug': 'Article Slug is invalid'})

        comment = article.add_comment(request_object.body, logged_in_user)
        return ResponseSuccess(Status.SUCCESS, comment)


class GetCommentsRequestObject(BaseRequestObject):
    """
    This class encapsulates the Request Object for Listing Articles
    """

    def __init__(self, entity_cls, article_id, page=1, per_page=None, order_by=(),
                 filters=None):
        """Initialize Request Object with parameters"""
        self.entity_cls = entity_cls
        self.article_id = article_id
        self.page = page
        self.per_page = per_page or active_config.PER_PAGE
        self.order_by = order_by
        self.filters = filters if filters else {}

    @classmethod
    def from_dict(cls, adict):
        """Initialize a ListRequestObject object from a dictionary."""
        invalid_req = InvalidRequestObject()

        if 'entity_cls' not in adict:
            invalid_req.add_error('entity_cls', 'is required')
        else:
            entity_cls = adict.pop('entity_cls')

        # Extract the pagination parameters from the input
        page = int(adict.pop('page', 1))
        per_page = int(adict.pop(
            'per_page', getattr(active_config, 'PER_PAGE', 10)))
        order_by = adict.pop('order_by', ())

        slug = None
        if 'slug' not in adict:
            invalid_req.add_error('slug', 'Article Slug is required')
        else:
            slug = adict.pop('slug')
        article = Article.find_by(slug=slug)

        # Check for invalid request conditions
        if page < 0:
            invalid_req.add_error('page', 'is invalid')

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity_cls, article.id, page, per_page, order_by, adict)


class GetCommentsUseCase(UseCase):
    """
    This class implements the usecase for listing all resources
    """

    def process_request(self, request_object):
        """Return a list of resources"""
        request_object.filters['article_id'] = request_object.article_id
        resources = (request_object.entity_cls.query
                     .filter(**request_object.filters)
                     .offset((request_object.page - 1) * request_object.per_page)
                     .limit(request_object.per_page)
                     .order_by(request_object.order_by)
                     .all())
        return ResponseSuccess(Status.SUCCESS, resources)


DeleteCommentRequestObject = RequestObjectFactory.construct(
    'DeleteCommentRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('token', str, {'required': True}),
     ('slug', str, {'required': True}),
     ('comment_id', str, {'required': True})])  # FIXME This should be a UUID


class DeleteCommentUseCase(UseCase):
    """Delete a comment from an article"""

    def process_request(self, request_object):
        """Process request for Deleting a comment from an article"""
        try:
            article = request_object.entity_cls.find_by(slug=request_object.slug)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'slug': 'Article Slug is invalid'})

        article.delete_comment(request_object.comment_id)
        return ResponseSuccess(Status.SUCCESS_WITH_NO_CONTENT)
