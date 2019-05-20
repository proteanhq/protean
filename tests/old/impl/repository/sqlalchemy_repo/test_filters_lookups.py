"""Module to test Repository extended functionality """
# Standard Library Imports
from datetime import datetime

# Protean
import pytest

from protean import Domain
from protean.utils.query import Q
from tests.old.support.sqlalchemy.human import SqlHuman as Human


class TestFiltersLookups:
    """Class to test Sqlalchemy Repository"""

    @pytest.fixture(scope='function', autouse=True)
    def humans(self):
        """Create sample humans in database"""
        return [
            Domain().get_repository(Human).create(
                name='John Doe', age='30',
                weight='13.45', date_of_birth='01-01-1989'),
            Domain().get_repository(Human).create(
                name='Jane Doe', age='25',
                weight='17.45', date_of_birth='23-08-1994'),
            Domain().get_repository(Human).create(
                name='Greg Manning', age='44',
                weight='23.45', date_of_birth='30-07-1975'),
            Domain().get_repository(Human).create(
                name='Red Dread', age='23',
                weight='33.45', date_of_birth='12-03-1996')
            ]

    def test_iexact_lookup(self, test_domain):
        """ Test the iexact lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(name__iexact='John doe')

        assert filtered_humans is not None
        assert filtered_humans.total == 1

    def test_contains_lookup(self, test_domain):
        """ Test the contains lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(name__contains='Doe')

        assert filtered_humans is not None
        assert filtered_humans.total == 2

    def test_icontains_lookup(self, humans, test_domain):
        """ Test the icontains lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(name__icontains='man')

        assert filtered_humans is not None
        assert filtered_humans.total == 1
        assert filtered_humans[0].id == humans[2].id

    def test_startswith_lookup(self, humans, test_domain):
        """ Test the startswith lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(name__startswith='John')

        assert filtered_humans is not None
        assert filtered_humans.total == 1
        assert filtered_humans[0].id == humans[0].id

    def test_endswith_lookup(self, humans, test_domain):
        """ Test the endswith lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(name__endswith='Doe')

        assert filtered_humans is not None
        assert filtered_humans.total == 2
        assert filtered_humans[0].id == humans[0].id

    def test_gt_lookup(self, humans, test_domain):
        """ Test the gt lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(age__gt=40)

        assert filtered_humans is not None
        assert filtered_humans.total == 1
        assert filtered_humans[0].id == humans[2].id

    def test_gte_lookup(self, humans, test_domain):
        """ Test the gte lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(age__gte=30).order_by(['age'])

        assert filtered_humans is not None
        assert filtered_humans.total == 2
        assert filtered_humans[0].id == humans[0].id

    def test_lt_lookup(self, humans, test_domain):
        """ Test the lt lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(weight__lt=15)

        assert filtered_humans is not None
        assert filtered_humans.total == 1
        assert filtered_humans[0].id == humans[0].id

    def test_lte_lookup(self, humans, test_domain):
        """ Test the lte lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(weight__lte=23.45)

        assert filtered_humans is not None
        assert filtered_humans.total == 3
        assert filtered_humans[0].id == humans[0].id

    def test_in_lookup(self, humans, test_domain):
        """ Test the lte lookup of the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(
            id__in=[humans[1].id, humans[3].id])
        assert filtered_humans.total == 2
        assert filtered_humans[0].id in [humans[1].id, humans[3].id]

    def test_date_lookup(self, humans, test_domain):
        """ Test the lookup of date fields for the Adapter """

        # Filter the entity and validate the results
        filtered_humans = test_domain.get_repository(Human).query.filter(date_of_birth__gt='1994-01-01')

        assert filtered_humans is not None
        assert filtered_humans.total == 2
        assert filtered_humans[0].id == humans[1].id

        filtered_humans = test_domain.get_repository(Human).query.filter(
            date_of_birth__lte=datetime(1989, 1, 1).date())

        assert filtered_humans is not None
        assert filtered_humans.total == 2
        assert filtered_humans[0].id == humans[0].id

    def test_q_filters(self, humans, test_domain):
        """ Test that complex filtering using the Q object"""

        # Filter by 2 conditions
        filtered_humans = test_domain.get_repository(Human).query.filter(Q(name__contains='Doe') & Q(age__gt=28))
        assert filtered_humans is not None
        assert filtered_humans.total == 1
        assert filtered_humans[0].id == humans[0].id

        # Try the same with negation
        filtered_humans = test_domain.get_repository(Human).query.filter(~Q(name__contains='Doe') & Q(age__gt=28))
        assert filtered_humans is not None
        assert filtered_humans.total == 1
        assert filtered_humans[0].id == humans[2].id

        # Try with basic or
        filtered_humans = test_domain.get_repository(Human).query.filter(Q(name__contains='Doe') | Q(age__gt=28))
        assert filtered_humans is not None
        assert filtered_humans.total == 3
        assert filtered_humans[0].id == humans[0].id

        # Try combination of and and or
        filtered_humans = test_domain.get_repository(Human).query.filter(
            Q(age__gte=27) | Q(weight__gt=15),
            name__contains='Doe')
        assert filtered_humans is not None
        assert filtered_humans.total == 2
        assert filtered_humans[0].id == humans[0].id

        # Try combination of and and or
        filtered_humans = test_domain.get_repository(Human).query.filter(
            (Q(weight__lte=20) | (Q(age__gt=30) & Q(name__endswith='Manning'))),
            Q(date_of_birth__gt='1994-01-01'))
        assert filtered_humans is not None
        assert filtered_humans.total == 1
        assert filtered_humans[0].id == humans[1].id
