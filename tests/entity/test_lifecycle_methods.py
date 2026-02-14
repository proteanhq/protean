import pytest

from protean.core.entity import BaseEntity
from protean.exceptions import ValidationError
from protean.fields import String

from .elements import Area, Building, BuildingStatus


class TestDefaults:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Area)
        test_domain.register(Building, part_of=Area)
        test_domain.init(traverse=False)

    def test_that_building_is_marked_as_done_if_above_4_floors(self):
        building = Building(name="Foo", floors=4)

        assert building.status == BuildingStatus.DONE.value

    def test_that_building_is_marked_as_done_if_below_4_floors(self):
        building = Building(name="Foo", floors=1)

        assert building.status == BuildingStatus.WIP.value

    def test_defaults_are_applied_after_field_validation(self):
        """Field validation happens during __init__ before defaults() can
        run.  So a required field without any value will still raise a
        ValidationError.

        However, defaults() can augment optional fields or override
        non-required field values after construction.
        """

        class Foo(BaseEntity):
            name: String(required=True, default="placeholder")

            def defaults(self):
                if self.name == "placeholder":
                    self.name = "bar"

        assert Foo().name == "bar"


class TestInvariantValidation:
    def test_that_building_cannot_be_WIP_if_above_4_floors(self, test_domain):
        test_domain.register(Area)
        test_domain.register(Building, part_of=Area)
        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            Building(name="Foo", floors=4, status=BuildingStatus.WIP.value)
