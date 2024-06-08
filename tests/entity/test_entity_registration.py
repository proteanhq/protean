from protean import BaseAggregate, BaseEntity
from protean.fields import String
from protean.utils import fully_qualified_name


class TestEntityRegistration:
    def test_manual_registration_of_entity(self, test_domain):
        class Post(BaseAggregate):
            name = String(max_length=50)

        class Comment(BaseEntity):
            content = String(max_length=500)

        test_domain.register(Post)
        test_domain.register(Comment, part_of=Post)

        assert fully_qualified_name(Comment) in test_domain.registry.entities
        assert Comment.meta_.part_of == Post

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.aggregate
        class Post:
            name = String(max_length=50)

        @test_domain.entity(part_of=Post)
        class Comment(BaseEntity):
            content = String(max_length=500)

        assert Comment.meta_.part_of == Post

    def test_setting_provider_in_decorator_based_registration_with_parameters(
        self, test_domain
    ):
        @test_domain.aggregate
        class Post:
            name = String(max_length=50)

        @test_domain.entity(part_of=Post)
        class Comment(BaseEntity):
            content = String(max_length=500)

        assert Comment.meta_.part_of == Post

    def test_register_entity_against_a_dummy_aggregate(self, test_domain):
        # Though the registration succeeds, this will eventually fail
        #   when the domain tries to resolve the aggregate.
        from protean.fields import String

        @test_domain.entity(part_of="foo")
        class FooBar:
            foo = String(max_length=50)

        assert FooBar.meta_.part_of == "foo"
