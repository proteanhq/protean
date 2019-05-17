"""Entities for Articles Aggregate"""
from datetime import datetime

from protean import Aggregate, Entity
from protean.core.field.basic import DateTime, Text, String, List
from protean.core.field.association import Reference, HasMany
from protean.utils.inflection import dasherize

from tests.support.domains.realworld.profile.domain.model.user import User


@Entity
class Comment:
    """Comment Entity"""

    created_at = DateTime(default=datetime.now(), required=True)
    updated_at = DateTime(default=datetime.now(), required=True)
    body = Text(required=True)

    user = Reference(User, required=True)
    article = Reference('Article', required=True)


@Aggregate(bounded_context='blog')
class Article:
    """Article Aggregate"""

    # FIXME `slug` should shadow Title's value with custom changes to value
    slug = String(max_length=255)
    title = String(max_length=255, required=True)
    description = String(max_length=255)
    body = Text()
    # FIXME Change field name to `tag_list` and map to `tagList` in serializer
    tagList = List()
    created_at = DateTime(default=datetime.now(), required=True)
    updated_at = DateTime(default=datetime.now(), required=True)

    author = Reference(User, required=True)

    comments = HasMany('Comment')

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
