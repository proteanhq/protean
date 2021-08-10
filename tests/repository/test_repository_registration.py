import pytest

from protean.core.field.basic import String
from protean.core.repository import BaseRepository
from protean.exceptions import IncorrectUsageError
from protean.utils import Database, fully_qualified_name

from .elements import Person, PersonRepository


class TestRepositoryInitialization:
    def test_that_base_repository_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseRepository()

    def test_that_repository_can_be_instantiated(self, test_domain):
        repo = PersonRepository()
        assert repo is not None


class TestRepositoryRegistration:
    def test_that_repository_can_be_registered_with_domain(self, test_domain):
        test_domain.register(PersonRepository)

        assert (
            fully_qualified_name(PersonRepository) in test_domain.registry.repositories
        )

    def test_that_repository_can_be_registered_via_annotations(self, test_domain):
        @test_domain.repository
        class AnnotatedRepository:
            def special_method(self):
                pass

            class Meta:
                aggregate_cls = Person

        assert (
            fully_qualified_name(AnnotatedRepository)
            in test_domain.registry.repositories
        )

    def test_that_repository_can_be_registered_via_annotations_with_aggregate_cls_parameter(
        self, test_domain
    ):
        @test_domain.repository(aggregate_cls=Person)
        class AnnotatedRepository:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedRepository)
            in test_domain.registry.repositories
        )

    def test_that_repository_cannot_be_registered_via_annotations_without_aggregate_cls(
        self, test_domain
    ):
        with pytest.raises(IncorrectUsageError):

            @test_domain.repository
            class AnnotatedRepository:
                def special_method(self):
                    pass

    def test_that_repository_can_be_retrieved_from_domain_by_its_aggregate_cls(
        self, test_domain
    ):
        test_domain.register(PersonRepository)

        assert isinstance(test_domain.repository_for(Person), PersonRepository)

    def test_that_fetching_an_unknown_repository_by_aggregate_cls_creates_one_automatically(
        self, test_domain
    ):
        repo = test_domain.repository_for(Person)
        assert repo.__class__.__name__ == "PersonRepository"

    # FIXME Uncomment
    # def test_that_repositories_can_only_be_associated_with_an_aggregate(
    #     self, test_domain
    # ):
    #     with pytest.raises(IncorrectUsageError) as exc:

    #         @test_domain.repository(aggregate_cls=Comment)
    #         class CommentRepository:
    #             def special_method(self):
    #                 pass

    #     assert exc.value.messages == {
    #         "entity": ["Repositories can only be associated with an Aggregate"]
    #     }

    def test_retrieving_custom_repository(self, test_domain):
        @test_domain.aggregate
        class GenericUser:
            name = String()

        @test_domain.repository(aggregate_cls=GenericUser)
        class GenericUserRepository:
            def special_method(self):
                pass

        assert isinstance(
            test_domain.repository_for(GenericUser), GenericUserRepository
        )
        assert (
            "ALL"
            in test_domain.providers._repositories[fully_qualified_name(GenericUser)]
        )
        assert (
            test_domain.providers._repositories[fully_qualified_name(GenericUser)][
                "ALL"
            ].__name__
            == "GenericUserRepository"
        )

    def test_retrieving_the_database_specific_repository(self, test_domain):
        test_domain.config["DATABASES"]["secondary"] = {
            "PROVIDER": "protean.adapters.repository.elasticsearch.ESProvider",
            "DATABASE": Database.ELASTICSEARCH.value,
            "DATABASE_URI": {"hosts": ["localhost"]},
        }

        @test_domain.aggregate
        class User:
            name = String()

        @test_domain.repository(aggregate_cls=User)
        class UserMemoryRepository:
            def special_method(self):
                pass

            class Meta:
                database = Database.MEMORY.value

        @test_domain.repository(aggregate_cls=User)
        class UserElasticRepository:
            def special_method(self):
                pass

            class Meta:
                database = Database.ELASTICSEARCH.value

        assert isinstance(test_domain.repository_for(User), UserMemoryRepository)

        # Next, we test for a secondary database repository by relinking the User aggregate
        @test_domain.aggregate
        class User:
            name = String()

            class Meta:
                provider = "secondary"

        assert isinstance(test_domain.repository_for(User), UserElasticRepository)
        # FIXME Reset test_domain?

    def test_incorrect_usage_error_on_repositories_associated_with_invalid_databases(
        self, test_domain
    ):
        @test_domain.aggregate
        class User:
            name = String()

            class Meta:
                provider = "secondary"

        with pytest.raises(IncorrectUsageError) as exc:

            @test_domain.repository(aggregate_cls=User)
            class CustomUserRepository:
                def special_method(self):
                    pass

                class Meta:
                    database = "UNKNOWN"

        assert exc.value.messages == {
            "entity": ["Repositories should be associated with a valid Database"]
        }
