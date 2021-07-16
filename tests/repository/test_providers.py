from typing import List

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Integer, String
from protean.core.repository import BaseRepository
from protean.globals import current_domain
from protean.utils import Database, fully_qualified_name


class PersonGeneric(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonCustomRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[PersonGeneric]:
        return current_domain.get_dao(PersonGeneric).filter(age__gte=minimum_age)

    class Meta:
        aggregate_cls = PersonGeneric


class PersonSQLite(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)

    class Meta:
        provider = "sqlite"


class PersonSQLiteGenericRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[PersonGeneric]:
        return current_domain.get_dao(PersonGeneric).filter(age__gte=minimum_age)

    class Meta:
        aggregate_cls = PersonSQLite


class PersonSQLiteCustomRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[PersonGeneric]:
        provider = current_domain.get_provider("sqlite")
        result = provider.raw("SELECT * FROM PERSON_GENERIC WHERE AGE >= 21")

        return result

    class Meta:
        aggregate_cls = PersonSQLite
        database = Database.SQLITE.value


class TestRepositoryConstructionAndRegistration:
    def test_default_repository_construction_and_registration(self, test_domain):
        test_domain.register(PersonGeneric)
        test_domain.repository_for(PersonGeneric)

        repo_cls_constructed = test_domain.providers._repositories[
            fully_qualified_name(PersonGeneric)
        ]["ALL"]
        repo_retrieved_from_domain = test_domain.repository_for(PersonGeneric)

        assert repo_cls_constructed.__name__ == "PersonGenericRepository"
        assert isinstance(repo_retrieved_from_domain, repo_cls_constructed)

    def test_custom_generic_repository_registration(self, test_domain):
        test_domain.register(PersonGeneric)
        test_domain.register(PersonCustomRepository)
        test_domain.repository_for(PersonGeneric)

        repo_cls_constructed = test_domain.providers._repositories[
            fully_qualified_name(PersonGeneric)
        ]["ALL"]
        repo_retrieved_from_domain = test_domain.repository_for(PersonGeneric)

        assert repo_cls_constructed.__name__ == "PersonCustomRepository"
        assert isinstance(repo_retrieved_from_domain, repo_cls_constructed)

    def test_default_repository_construction_and_registration_for_non_memory_database(
        self, test_domain
    ):
        test_domain.register(PersonSQLite)
        test_domain.repository_for(PersonSQLite)

        repo_cls_constructed = test_domain.providers._repositories[
            fully_qualified_name(PersonSQLite)
        ]["ALL"]
        repo_retrieved_from_domain = test_domain.repository_for(PersonSQLite)

        assert repo_cls_constructed.__name__ == "PersonSQLiteRepository"
        assert isinstance(repo_retrieved_from_domain, repo_cls_constructed)

    def test_custom_repository_construction_and_registration_for_non_memory_database(
        self, test_domain
    ):
        test_domain.register(PersonSQLite)
        test_domain.register(PersonSQLiteCustomRepository)
        test_domain.repository_for(PersonSQLite)

        repo_cls_constructed = test_domain.providers._repositories[
            fully_qualified_name(PersonSQLite)
        ]["SQLITE"]
        repo_retrieved_from_domain = test_domain.repository_for(PersonSQLite)

        assert repo_cls_constructed.__name__ == "PersonSQLiteCustomRepository"
        assert isinstance(repo_retrieved_from_domain, repo_cls_constructed)

    def test_that_sqlite_repository_is_chosen_over_generic_provider(self, test_domain):
        test_domain.register(PersonSQLite)
        test_domain.register(PersonSQLiteGenericRepository)
        test_domain.register(PersonSQLiteCustomRepository)
        test_domain.repository_for(PersonSQLite)

        repo_cls_constructed = test_domain.providers._repositories[
            fully_qualified_name(PersonSQLite)
        ]["SQLITE"]
        repo_retrieved_from_domain = test_domain.repository_for(PersonSQLite)

        assert repo_cls_constructed.__name__ == "PersonSQLiteCustomRepository"
        assert isinstance(repo_retrieved_from_domain, repo_cls_constructed)
