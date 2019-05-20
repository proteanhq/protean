"""User Aggregate"""
from __future__ import annotations

from datetime import datetime

from passlib.hash import pbkdf2_sha256

# Protean
from protean import Domain
from protean import Aggregate, Entity, ValueObject
from protean.core.field.basic import String, Text, DateTime
from protean.core.field.association import HasMany, Reference
from protean.core.field.embedded import ValueObjectField


@ValueObject(aggregate='user')
class Email:
    """An email address, with two clearly identified parts:
        * local_part
        * domain_part
    """

    address = String(max_length=254)

    def __init__(self, *template, local_part=None, domain_part=None, **kwargs):
        super(Email, self).__init__(*template, **kwargs)
        self.local_part = local_part
        self.domain_part = domain_part

        if self.local_part and self.domain_part:
            self.address = '@'.join([self.local_part, self.domain_part])

    @classmethod
    def build(cls, **values):
        assert 'address' in values

        if '@' not in values['address']:
            raise ValueError('Email address is invalid. Must contain \'@\'')
        local_part, _, domain_part = values['address'].partition('@')

        return cls.build_from_parts(local_part, domain_part)

    @classmethod
    def build_from_parts(cls, local_part, domain_part):
        if len(local_part) + len(domain_part) > 255:
            raise ValueError('Email address is too long')
        return cls(local_part=local_part, domain_part=domain_part)

    def _clone_with_values(self, **kwargs):
        # FIXME Find a way to do this generically and move method to `BaseValueObject`
        local = kwargs.pop('local', None)
        domain = kwargs.pop('domain', None)
        return Email(local_part=local or self.local_part,
                     domain_part=domain or self.domain_part)


@Aggregate(bounded_context='identity')
class User:
    bio = Text()
    email = ValueObjectField(Email)
    image = String(max_length=1024)  # FIXME File VO/URL?
    password = String(max_length=255)  # FIXME Hide this from appearing in to_dict or other attr loops
    token = String(max_length=1024)
    username = String(max_length=50)

    @classmethod
    def build(cls, *template, **kwargs):
        """In addition to instantiating a User object:
            * hash password
        """
        instance = super(User, cls).build(*template, **kwargs)

        instance.password = pbkdf2_sha256.hash(instance.password)

        if not instance.token:
            import uuid
            instance.token = uuid.uuid4()

        return instance

    follows = HasMany('Follower', via='follower_id')
    followed_by = HasMany('Follower')

    favorites = HasMany('Favorite')

    def follow(self, profile):
        Domain().get_repository(Follower).create(user_id=profile.id, follower_id=self.id)
        return self

    def unfollow(self, profile):
        follower = Domain().get_repository(Follower).find_by(user_id=profile.id, follower_id=self.id)
        Domain().get_repository(Follower).delete(follower)
        return self

    # FIXME Should we expect an article here, or just an identifier
    def favorite(self, article):
        Domain().get_repository(Favorite).create(user=self, article_id=article.id)
        return self

    def unfavorite(self, article):  # FIXME Should we expect an Identifier here, or an article object
        favorite = Domain().get_repository(Favorite).find_by(user_id=self.id, article_id=article.id)
        Domain().get_repository(Favorite).delete(favorite)
        return self


@Entity(aggregate='user')
class Follower:
    """Follower Entity"""

    user = Reference(User)
    follower = Reference(User)
    followed_on = DateTime(default=datetime.now())


@Entity(aggregate='user')
class Favorite:
    """Favorite Entity"""

    user = Reference(User, required=True)
    article = Reference('Article', required=True)
    favorited_at = DateTime(default=datetime.now(), required=True)
