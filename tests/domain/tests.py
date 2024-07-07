import pytest

from protean import BaseAggregate, BaseEntity, Domain
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import DateTime, HasMany, HasOne, Reference, String, Text
from protean.reflection import declared_fields
from protean.utils import fully_qualified_name

from .elements import UserAggregate, UserEntity, UserFoo, UserVO


def test_domain_name_string():
    domain = Domain(__file__, "Foo", load_toml=False)

    assert str(domain) == "Domain: Foo"


class TestElementRegistration:
    def test_that_only_recognized_element_types_can_be_registered(self, test_domain):
        with pytest.raises(NotSupportedError) as exc:
            test_domain.registry.register_element(UserFoo)

        assert exc.value.args[0] == "Element `UserFoo` is not a valid element class"

    def test_register_aggregate_with_domain(self, test_domain):
        test_domain.registry.register_element(UserAggregate)

        assert test_domain.registry.aggregates != {}
        assert fully_qualified_name(UserAggregate) in test_domain.registry.aggregates

    def test_register_entity_with_domain(self, test_domain):
        test_domain.registry.register_element(UserEntity)

        assert fully_qualified_name(UserEntity) in test_domain.registry.entities

    def test_register_value_object_with_domain(self, test_domain):
        test_domain.registry.register_element(UserVO)

        assert fully_qualified_name(UserVO) in test_domain.registry.value_objects

    def test_that_an_improperly_subclassed_element_cannot_be_registered(
        self, test_domain
    ):
        from protean.fields import String

        class Foo:
            pass

        class Bar(Foo):
            foo = String(max_length=50)

        with pytest.raises(NotSupportedError) as exc:
            test_domain.register(Bar)

        assert exc.value.args[0] == "Element `Bar` is not a valid element class"

    def test_options_are_validated_on_element_registration(self, test_domain):
        class Foo(BaseAggregate):
            foo = String(max_length=50)

        with pytest.raises(ConfigurationError) as exc:
            test_domain.register(Foo, foo="bar")

        assert exc.value.args[0] == "Unknown option(s) {'foo'}"


class TestDomainAnnotations:
    # Individual test cases for registering domain elements with
    #   domain decorators are present in their respective test folders.

    def test_that_only_recognized_element_types_can_be_registered(self, test_domain):
        # Standard Library Imports
        from enum import Enum

        from protean.fields import String

        class DummyElement(Enum):
            FOO = "FOO"

        class FooBar:
            foo = String(max_length=50)

        with pytest.raises(IncorrectUsageError):
            test_domain._register_element(DummyElement.FOO, FooBar, part_of="foo")


class TestDomainLevelClassResolution:
    class TestWhenDomainIsActive:
        def test_that_unknown_class_reference_is_tracked_at_the_domain_level(
            self, test_domain
        ):
            class Post(BaseAggregate):
                content = Text(required=True)
                comments = HasMany("Comment")

            test_domain.register(Post)

            assert "Comment" in test_domain._pending_class_resolutions
            # The content in _pending_class_resolutions is dict -> tuple (str, tuple) array
            # key: field name
            # value: tuple of (Resolution Type, (Field Object, Owning Domain Element)) for Associations
            # value: tuple of (Resolution Type, (Domain Element)) for Meta links
            assert (
                test_domain._pending_class_resolutions["Comment"][0][1][0]
                == declared_fields(Post)["comments"]
            )

        def test_that_class_referenced_is_resolved_as_soon_as_element_is_registered(
            self, test_domain
        ):
            class Post(BaseAggregate):
                content = Text(required=True)
                comments = HasMany("Comment")

            test_domain.register(Post)

            # Still a string reference
            assert isinstance(declared_fields(Post)["comments"].to_cls, str)

            class Comment(BaseEntity):
                content = Text()
                added_on = DateTime()

                post = Reference("Post")

            # Still a string reference
            assert isinstance(declared_fields(Comment)["post"].to_cls, str)

            assert (
                len(test_domain._pending_class_resolutions) == 1
            )  # Comment has not been registered yet

            # Registering `Comment` resolves references in both `Comment` and `Post` classes
            test_domain.register(Comment, part_of=Post)
            test_domain._resolve_references()

            assert declared_fields(Post)["comments"].to_cls == Comment
            assert declared_fields(Comment)["post"].to_cls == Post

            assert len(test_domain._pending_class_resolutions) == 0

    class TestWhenDomainHasNotBeenActivatedYet:
        @pytest.fixture(autouse=True)
        def test_domain(self):
            from protean.domain import Domain

            domain = Domain(__file__, "Test", load_toml=False)
            domain.config["databases"]["memory"] = {"provider": "memory"}
            yield domain

        def test_that_class_reference_is_tracked_at_the_domain_level(self):
            domain = Domain(__file__, load_toml=False)

            class Post(BaseAggregate):
                content = Text(required=True)
                comments = HasMany("Comment")

            domain.register(Post)

            # Still a string
            assert isinstance(declared_fields(Post)["comments"].to_cls, str)

            class Comment(BaseEntity):
                content = Text()
                added_on = DateTime()

                post = Reference("Post")

            domain.register(Comment, part_of=Post)

            assert len(domain._pending_class_resolutions) == 2
            assert all(
                field_name in domain._pending_class_resolutions
                for field_name in ["Comment", "Post"]
            )

        def test_that_class_reference_is_resolved_on_domain_initialization(self):
            domain = Domain(__file__, "Inline Domain", load_toml=False)

            class Post(BaseAggregate):
                content = Text(required=True)
                comments = HasMany("Comment")

            domain.register(Post)

            # Still a string
            assert isinstance(declared_fields(Post)["comments"].to_cls, str)

            class Comment(BaseEntity):
                content = Text()
                added_on = DateTime()

                post = Reference("Post")

            domain.register(Comment, part_of=Post)

            # `init` resolves references
            domain.init(traverse=False)

            # Check for resolved references
            assert declared_fields(Post)["comments"].to_cls == Comment
            assert declared_fields(Comment)["post"].to_cls == Post

            assert len(domain._pending_class_resolutions) == 0

        def test_that_domain_throws_exception_on_unknown_class_references_during_activation(
            self,
        ):
            domain = Domain(__file__, "Inline Domain", load_toml=False)

            class Post(BaseAggregate):
                content = Text(required=True)
                comments = HasMany("Comment")

            domain.register(Post)

            # Still a string
            assert isinstance(declared_fields(Post)["comments"].to_cls, str)

            class Comment(BaseEntity):
                content = Text()
                added_on = DateTime()

                post = Reference("Post")
                foo = Reference("Foo")

            domain.register(Comment, part_of=Post)

            with pytest.raises(ConfigurationError) as exc:
                domain.init()

            assert (
                exc.value.args[0]["element"]
                == "Element Foo not registered in domain Inline Domain"
            )

            # Remove domain context manually, as we lost it when the exception was raised
            from protean.globals import _domain_context_stack

            _domain_context_stack.pop()

    class TestWithDifferentTypesOfAssociations:
        def test_that_has_many_field_references_are_resolved(self, test_domain):
            class Post(BaseAggregate):
                content = Text(required=True)
                comments = HasMany("Comment")

            class Comment(BaseEntity):
                content = Text()
                added_on = DateTime()

                post = Reference("Post")

            test_domain.register(Post)
            test_domain.register(Comment, part_of=Post)
            test_domain._resolve_references()

            assert declared_fields(Post)["comments"].to_cls == Comment
            assert declared_fields(Comment)["post"].to_cls == Post

            assert len(test_domain._pending_class_resolutions) == 0

        def test_that_has_one_field_references_are_resolved(self, test_domain):
            class Account(BaseAggregate):
                email = String(
                    required=True, max_length=255, unique=True, identifier=True
                )
                author = HasOne("Author")

            class Author(BaseEntity):
                first_name = String(required=True, max_length=25)
                last_name = String(max_length=25)
                account = Reference("Account")

            test_domain.register(Account)
            test_domain.register(Author, part_of=Account)
            test_domain._resolve_references()

            assert declared_fields(Account)["author"].to_cls == Author
            assert declared_fields(Author)["account"].to_cls == Account

            assert len(test_domain._pending_class_resolutions) == 0
