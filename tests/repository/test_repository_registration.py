import pytest

from protean.core.repository import BaseRepository
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import fully_qualified_name

from .elements import Person, PersonRepository


class TestRepositoryInitialization:
    def test_that_base_repository_class_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseRepository()

    def test_that_repository_can_be_instantiated(self, test_domain):
        repo = test_domain.repository_for(Person)
        assert repo is not None


class TestRepositoryRegistration:
    def test_that_repository_can_be_registered_with_domain(self, test_domain):
        test_domain.register(PersonRepository, part_of=Person)

        assert (
            fully_qualified_name(PersonRepository) in test_domain.registry.repositories
        )

    def test_that_repository_can_be_registered_via_annotations_with_part_of_parameter(
        self, test_domain
    ):
        @test_domain.repository(part_of=Person)
        class AnnotatedRepository:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedRepository)
            in test_domain.registry.repositories
        )

    def test_that_repository_cannot_be_registered_via_annotations_without_part_of(
        self, test_domain
    ):
        with pytest.raises(IncorrectUsageError):

            @test_domain.repository
            class AnnotatedRepository:
                def special_method(self):
                    pass

    def test_that_repository_can_be_retrieved_from_domain_by_its_part_of(
        self, test_domain
    ):
        test_domain.register(PersonRepository, part_of=Person)

        assert isinstance(test_domain.repository_for(Person), PersonRepository)

    def test_that_fetching_an_unknown_repository_by_part_of_creates_one_automatically(
        self, test_domain
    ):
        repo = test_domain.repository_for(Person)
        assert repo.__class__.__name__ == "PersonRepository"

    # FIXME Uncomment
    # def test_that_repositories_can_only_be_associated_with_an_aggregate(
    #     self, test_domain
    # ):
    #     with pytest.raises(IncorrectUsageError) as exc:

    #         @test_domain.repository(part_of=Comment)
    #         class CommentRepository:
    #             def special_method(self):
    #                 pass

    #     assert exc.value.messages == {
    #         "_entity": ["Repositories can only be associated with an Aggregate"]
    #     }

    def test_retrieving_custom_repository(self, test_domain):
        @test_domain.aggregate
        class GenericUser:
            name: str | None = None

        @test_domain.repository(part_of=GenericUser)
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

    @pytest.mark.elasticsearch
    def test_retrieving_the_database_specific_repository(self, test_domain):
        test_domain.config["databases"]["secondary"] = {
            "provider": "elasticsearch",
            "database_uri": '{"hosts": ["localhost"]}',
        }
        test_domain._initialize()

        @test_domain.aggregate
        class User:
            name: str | None = None

        @test_domain.repository(part_of=User, database="memory")
        class UserMemoryRepository:
            def special_method(self):
                pass

        @test_domain.repository(part_of=User, database="elasticsearch")
        class UserElasticRepository:
            def special_method(self):
                pass

        assert isinstance(test_domain.repository_for(User), UserMemoryRepository)

        # Next, we test for a secondary database repository by relinking the User aggregate
        @test_domain.aggregate(provider="secondary")
        class User:
            name: str | None = None

        assert isinstance(test_domain.repository_for(User), UserElasticRepository)
        # FIXME Reset test_domain?

    def test_incorrect_usage_error_on_repositories_associated_with_invalid_databases(
        self, test_domain
    ):
        @test_domain.aggregate(provider="secondary")
        class User:
            name: str | None = None

        with pytest.raises(IncorrectUsageError) as exc:

            @test_domain.repository(part_of=User, database="UNKNOWN")
            class CustomUserRepository:
                def special_method(self):
                    pass

        assert exc.value.args[0] == (
            "Repository `CustomUserRepository` should be associated with a valid Database"
        )
