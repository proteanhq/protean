import pytest

from protean.exceptions import ValidationError

from .elements import Area, Building, BuildingStatus


class TestDefaults:
    def test_that_building_is_marked_as_done_if_above_4_floors(self):
        building = Building(name="Foo", floors=4)

        assert building.status == BuildingStatus.DONE.value

    def test_that_building_is_marked_as_done_if_below_4_floors(self):
        building = Building(name="Foo", floors=1)

        assert building.status == BuildingStatus.WIP.value


class TestClean:
    def test_that_building_cannot_be_WIP_if_above_4_floors(self, test_domain):
        test_domain.register(Building)
        test_domain.register(Area)
        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            Building(name="Foo", floors=4, status=BuildingStatus.WIP.value)
