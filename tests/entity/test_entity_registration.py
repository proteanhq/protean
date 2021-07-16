from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.field.basic import String
from protean.utils import fully_qualified_name


class TestEntityRegistration:
    def test_manual_registration_of_entity(self, test_domain):
        class Post(BaseAggregate):
            name = String(max_length=50)

        class Comment(BaseEntity):
            content = String(max_length=500)

            class Meta:
                aggregate_cls = Post

        test_domain.register(Post)
        test_domain.register(Comment)

        assert fully_qualified_name(Comment) in test_domain.registry.entities
        assert Comment.meta_.aggregate_cls == Post

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.aggregate
        class Post:
            name = String(max_length=50)

        @test_domain.entity
        class Comment(BaseEntity):
            content = String(max_length=500)

            class Meta:
                aggregate_cls = Post

        assert Comment.meta_.aggregate_cls == Post

    def test_setting_provider_in_decorator_based_registration_with_parameters(
        self, test_domain
    ):
        @test_domain.aggregate
        class Post:
            name = String(max_length=50)

        @test_domain.entity(aggregate_cls=Post)
        class Comment(BaseEntity):
            content = String(max_length=500)

        assert Comment.meta_.aggregate_cls == Post

    def test_register_entity_against_a_dummy_aggregate(self, test_domain):
        # Though the registration succeeds, this will eventually fail
        #   when the domain tries to resolve the aggregate.
        from protean.core.field.basic import String

        @test_domain.entity(aggregate_cls="foo")
        class FooBar:
            foo = String(max_length=50)

        assert FooBar.meta_.aggregate_cls == "foo"
