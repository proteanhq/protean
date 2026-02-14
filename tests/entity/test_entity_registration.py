from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.utils import fully_qualified_name


class TestEntityRegistration:
    def test_manual_registration_of_entity(self, test_domain):
        class Post(BaseAggregate):
            name: str | None = None

        class Comment(BaseEntity):
            content: str | None = None

        test_domain.register(Post)
        test_domain.register(Comment, part_of=Post)

        assert fully_qualified_name(Comment) in test_domain.registry.entities
        assert Comment.meta_.part_of == Post

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.aggregate
        class Post:
            name: str | None = None

        @test_domain.entity(part_of=Post)
        class Comment(BaseEntity):
            content: str | None = None

        assert Comment.meta_.part_of == Post

    def test_setting_provider_in_decorator_based_registration_with_parameters(
        self, test_domain
    ):
        @test_domain.aggregate
        class Post:
            name: str | None = None

        @test_domain.entity(part_of=Post)
        class Comment(BaseEntity):
            content: str | None = None

        assert Comment.meta_.part_of == Post

    def test_register_entity_against_a_dummy_aggregate(self, test_domain):
        # Though the registration succeeds, this will eventually fail
        #   when the domain tries to resolve the aggregate.
        @test_domain.entity(part_of="foo")
        class FooBar:
            foo: str | None = None

        assert FooBar.meta_.part_of == "foo"
