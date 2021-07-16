import pytest

from protean.utils.query import Q

from .elements import Person


class TestConjunctions:
    """Class that holds tests cases for Conjunctions (AND, OR, NeG)"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    @pytest.fixture
    def create_3_people(self, test_domain):
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

    @pytest.fixture
    def create_5_people(self, test_domain):
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )
        test_domain.get_dao(Person).create(
            id=5, first_name="Leslie", age=6, last_name="Underwood"
        )
        test_domain.get_dao(Person).create(
            id=6, first_name="Dave", age=6, last_name="Carrie"
        )

    def test_that_kwargs_to_filter_are_ANDed_by_default(
        self, test_domain, create_3_people
    ):
        q1 = test_domain.get_dao(Person).query.filter(last_name="John", age=3)
        assert q1.total == 1

    def test_that_kwargs_to_exclude_are_ORed_by_default(
        self, test_domain, create_3_people
    ):
        q1 = test_domain.get_dao(Person).query.exclude(last_name="John", age=3)
        assert q1.total == 1

        q2 = test_domain.get_dao(Person).query.exclude(last_name="Carrie", age=10)
        assert q2.total == 2

    def test_straightforward_AND_of_two_criteria(self, test_domain, create_3_people):
        # Filter by the Owner
        q1 = test_domain.get_dao(Person).query.filter(Q(last_name="John") & Q(age=3))
        assert q1.total == 1

    def test_straightforward_OR_of_two_criteria(self, test_domain, create_3_people):
        q1 = test_domain.get_dao(Person).query.filter(Q(last_name="John") | Q(age=3))
        assert q1.total == 2

    def test_combination_of_AND_followed_by_OR(self, test_domain, create_5_people):
        q1 = test_domain.get_dao(Person).query.filter(
            Q(last_name="John", first_name="Jean") | Q(age=6)
        )
        assert q1.total == 4

        q2 = test_domain.get_dao(Person).query.filter(Q(last_name="John") | Q(age=6))
        assert q2.total == 5

        q3 = test_domain.get_dao(Person).query.filter(
            (Q(last_name="John") & Q(age=7)) | (Q(last_name="Carrie") & Q(age=6))
        )
        assert q3.total == 3

    def test_combination_of_OR_followed_by_AND(self, test_domain, create_5_people):
        q1 = test_domain.get_dao(Person).query.filter(
            (Q(last_name="John") | Q(age=7)) & (Q(last_name="Carrie") | Q(age=6))
        )
        assert q1.total == 0

        q2 = test_domain.get_dao(Person).query.filter(
            (Q(last_name="John") | Q(age__gte=3))
            & (Q(first_name="Jean") | Q(first_name="Murdock"))
        )
        assert q2.total == 2

    def test_NEG_of_criteria(self, test_domain, create_5_people):
        q1 = test_domain.get_dao(Person).query.filter(~Q(last_name="John"))
        assert q1.total == 3

        q2 = test_domain.get_dao(Person).query.filter(~Q(last_name="John") | ~Q(age=7))
        assert q2.total == 4

    def test_empty_resultset_is_returned_correctly(self, test_domain, create_3_people):
        q1 = test_domain.get_dao(Person).query.filter(last_name="XYZ", age=100)
        assert q1.total == 0
