import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.repository import BaseRepository, repository_factory
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import String
from protean.utils import _fully_qualified_name
from tests.shared import ELASTICSEARCH_URI

from .elements import Person, PersonRepository


class TestRepositoryInitialization:
    def test_that_base_repository_class_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseRepository()

    def test_that_repository_can_be_instantiated(self, test_domain):
        repo = test_domain.repository_for(Person)
        assert repo is not None

    def test_that_base_repository_has_no_delete_or_remove_method(self):
        assert not hasattr(BaseRepository, "delete")
        assert not hasattr(BaseRepository, "remove")


class TestRepositoryRegistration:
    def test_that_repository_can_be_registered_with_domain(self, test_domain):
        test_domain.register(PersonRepository, part_of=Person)

        assert (
            _fully_qualified_name(PersonRepository) in test_domain.registry.repositories
        )

    def test_that_repository_can_be_registered_via_annotations_with_part_of_parameter(
        self, test_domain
    ):
        @test_domain.repository(part_of=Person)
        class AnnotatedRepository:
            def special_method(self):
                pass

        assert (
            _fully_qualified_name(AnnotatedRepository)
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

    def test_that_repositories_can_only_be_associated_with_an_aggregate(
        self, test_domain
    ):
        @test_domain.entity(part_of=Person)
        class Comment(BaseEntity):
            body: String(max_length=500)

        with pytest.raises(IncorrectUsageError) as exc:

            @test_domain.repository(part_of=Comment)
            class CommentRepository:
                def special_method(self):
                    pass

        assert (
            exc.value.args[0]
            == "Repository `CommentRepository` can only be associated with an Aggregate"
        )

    def test_retrieving_custom_repository(self, test_domain):
        @test_domain.aggregate
        class GenericUser:
            name: String()

        @test_domain.repository(part_of=GenericUser)
        class GenericUserRepository:
            def special_method(self):
                pass

        assert isinstance(
            test_domain.repository_for(GenericUser), GenericUserRepository
        )
        assert (
            "ALL"
            in test_domain.databases._repositories[_fully_qualified_name(GenericUser)]
        )
        assert (
            test_domain.databases._repositories[_fully_qualified_name(GenericUser)][
                "ALL"
            ].__name__
            == "GenericUserRepository"
        )

    @pytest.mark.elasticsearch
    def test_retrieving_the_database_specific_repository(self, test_domain):
        test_domain.config["databases"]["secondary"] = {
            "provider": "elasticsearch",
            "database_uri": ELASTICSEARCH_URI,
        }
        test_domain._initialize()

        @test_domain.aggregate
        class User:
            name: String()

        @test_domain.repository(part_of=User, database_type="memory")
        class UserMemoryRepository:
            def special_method(self):
                pass

        @test_domain.repository(part_of=User, database_type="elasticsearch")
        class UserElasticRepository:
            def special_method(self):
                pass

        assert isinstance(test_domain.repository_for(User), UserMemoryRepository)

        # Next, we test for a secondary database repository by relinking the User aggregate
        @test_domain.aggregate(database="secondary")
        class User:
            name: String()

        assert isinstance(test_domain.repository_for(User), UserElasticRepository)

    def test_init_rejects_a_repository_bound_to_an_unknown_database_type(
        self, test_domain
    ):
        @test_domain.aggregate
        class User:
            name: String()

        @test_domain.repository(part_of=User, database_type="UNKNOWN")
        class CustomUserRepository:
            def special_method(self):
                pass

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.args[0].startswith(
            "`CustomUserRepository` declares database_type `UNKNOWN`, which no "
            "registered database adapter provides. Use `ALL` or one of: "
        )


class TestRepositoryOnEventSourcedAggregate:
    def test_registering_a_repository_for_an_event_sourced_aggregate_raises(
        self, test_domain
    ):
        @test_domain.aggregate(event_sourced=True)
        class Account:
            name: String()

        with pytest.raises(IncorrectUsageError) as exc:

            @test_domain.repository(part_of=Account)
            class AccountRepository:
                def find_active(self):
                    return []

        assert exc.value.code == "USAGE_REPOSITORY_ON_EVENT_SOURCED_AGGREGATE"
        assert exc.value.location == "Domain.register"
        assert exc.value.args[0] == (
            "Repository `AccountRepository` cannot be associated with `Account`, "
            "which is an event-sourced aggregate. To add custom methods, "
            "subclass `BaseEventSourcedRepository` and register the subclass "
            "with `domain.register(<Repository>, part_of=Account)`."
        )

    def test_a_string_part_of_naming_an_event_sourced_aggregate_raises_at_init(
        self, test_domain
    ):
        @test_domain.aggregate(event_sourced=True)
        class Account:
            name: String()

        @test_domain.repository(part_of="Account")
        class AccountRepository:
            def find_active(self):
                return []

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.code == "USAGE_REPOSITORY_ON_EVENT_SOURCED_AGGREGATE"
        assert exc.value.location == "Domain.init"
        assert (
            "`AccountRepository` cannot be associated with `Account`"
            in (exc.value.args[0])
        )
        assert "`BaseEventSourcedRepository`" in exc.value.args[0]
        assert "`domain.register(<Repository>, part_of=Account)`" in exc.value.args[0]

    def test_a_repository_registered_before_the_aggregate_raises_at_init(
        self, test_domain
    ):
        class Account(BaseAggregate):
            name: String()

        class AccountRepository(BaseRepository):
            def find_active(self):
                return []

        test_domain.register(AccountRepository, part_of=Account)
        test_domain.register(Account, event_sourced=True)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.code == "USAGE_REPOSITORY_ON_EVENT_SOURCED_AGGREGATE"
        assert exc.value.location == "Domain.init"
        assert (
            "`AccountRepository` cannot be associated with `Account`"
            in (exc.value.args[0])
        )

    def test_an_auto_constructed_repository_is_not_refused(self, test_domain):
        @test_domain.aggregate(event_sourced=True)
        class Account:
            name: String()

        class AccountRepository(BaseRepository):
            pass

        repository_cls = repository_factory(
            AccountRepository, test_domain, part_of=Account, _auto_constructed=True
        )

        assert repository_cls.meta_.part_of is Account

    def test_a_repository_for_a_state_based_aggregate_is_returned(self, test_domain):
        @test_domain.aggregate
        class Account:
            name: String()

        @test_domain.repository(part_of=Account)
        class AccountRepository:
            def find_active(self):
                return []

        test_domain.init(traverse=False)

        assert isinstance(test_domain.repository_for(Account), AccountRepository)

    def test_a_string_part_of_naming_a_state_based_aggregate_is_returned(
        self, test_domain
    ):
        @test_domain.aggregate
        class Account:
            name: String()

        @test_domain.repository(part_of="Account")
        class AccountRepository:
            def find_active(self):
                return []

        test_domain.init(traverse=False)

        assert isinstance(test_domain.repository_for(Account), AccountRepository)
