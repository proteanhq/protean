import pytest

from protean import BaseEntity
from protean.fields import String
from protean.exceptions import ValidationError

from .elements import Area, Building, BuildingStatus


class TestDefaults:
    def test_that_building_is_marked_as_done_if_above_4_floors(self):
        building = Building(name="Foo", floors=4)

        assert building.status == BuildingStatus.DONE.value

    def test_that_building_is_marked_as_done_if_below_4_floors(self):
        building = Building(name="Foo", floors=1)

        assert building.status == BuildingStatus.WIP.value

    def test_defaults_are_applied_before_validation(self):
        class Foo(BaseEntity):
            name = String(required=True)

            def defaults(self):
                self.name = "bar"

        assert Foo().name == "bar"


class TestInvariantValidation:
    def test_that_building_cannot_be_WIP_if_above_4_floors(self, test_domain):
        test_domain.register(Area)
        test_domain.register(Building, part_of=Area)
        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            Building(name="Foo", floors=4, status=BuildingStatus.WIP.value)
