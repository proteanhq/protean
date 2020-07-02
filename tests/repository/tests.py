# Protean
import pytest

from protean.core.exceptions import IncorrectUsageError
from protean.core.repository.base import BaseRepository
from protean.utils import fully_qualified_name

# Local/Relative Imports
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

        assert fully_qualified_name(PersonRepository) in test_domain.repositories

    def test_that_repository_can_be_registered_via_annotations(self, test_domain):
        @test_domain.repository
        class AnnotatedRepository:
            def special_method(self):
                pass

            class Meta:
                aggregate_cls = Person

        assert fully_qualified_name(AnnotatedRepository) in test_domain.repositories

    def test_that_repository_can_be_registered_via_annotations_with_aggregate_cls_parameter(
        self, test_domain
    ):
        @test_domain.repository(aggregate_cls=Person)
        class AnnotatedRepository:
            def special_method(self):
                pass

        assert fully_qualified_name(AnnotatedRepository) in test_domain.repositories

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
