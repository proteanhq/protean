"""Entities for Articles Aggregate"""
from datetime import datetime

from protean import Aggregate, Entity
from protean.core import field
from protean.utils.inflection import dasherize

from tests.support.domains.realworld.profile.domain.model.user import User


@Entity
class Comment:
    """Comment Entity"""

    created_at = field.DateTime(default=datetime.now(), required=True)
    updated_at = field.DateTime(default=datetime.now(), required=True)
    body = field.Text(required=True)

    user = field.Reference(User, required=True)
    article = field.Reference('Article', required=True)


@Aggregate(bounded_context='blog', root=True)
class Article:
    """Article Aggregate"""

    # FIXME `slug` should shadow Title's value with custom changes to value
    slug = field.String(max_length=255)
    title = field.String(max_length=255, required=True)
    description = field.String(max_length=255)
    body = field.Text()
    # FIXME Change field name to `tag_list` and map to `tagList` in serializer
    tagList = field.List()
    created_at = field.DateTime(default=datetime.now(), required=True)
    updated_at = field.DateTime(default=datetime.now(), required=True)

    author = field.Reference(User, required=True)

    comments = field.association.HasMany('Comment')

    @classmethod
    def build(cls, *template, **kwargs):
        """In addition to instantiating a User object:
            * hash password
        """
        instance = super(Article, cls).build(*template, **kwargs)

        instance.slug = dasherize(instance.title.lower())

        return instance

    def add_comment(self, body, user):
        """Add a comment under this article"""
        return Comment.create(body=body, user=user, article=self)

    def delete_comment(self, comment_id):
        """Add a comment under this article"""
        comment = Comment.get(comment_id)
        comment.delete()
