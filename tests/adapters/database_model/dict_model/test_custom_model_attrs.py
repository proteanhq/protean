"""Tests verifying that custom model attributes survive dynamic class
creation via ``type()`` in ``decorate_database_model_class``."""

import pytest

from .elements import Widget, WidgetCustomModel


class TestCustomModelAttributePreservation:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Widget)
        test_domain.register(WidgetCustomModel, part_of=Widget)
        test_domain.init(traverse=False)

    def test_custom_from_entity_override_is_used(self, test_domain):
        model_cls = test_domain.repository_for(Widget)._database_model
        widget = Widget(name="bolt", weight=10)
        model_obj = model_cls.from_entity(widget)

        # The custom from_entity upper-cases the name
        assert model_obj["name"] == "BOLT"

    def test_custom_staticmethod_is_callable(self, test_domain):
        model_cls = test_domain.repository_for(Widget)._database_model
        assert model_cls.custom_static() == "static-ok"

    def test_custom_property_is_accessible(self, test_domain):
        model_cls = test_domain.repository_for(Widget)._database_model
        # Properties need an instance; use a dummy instance
        instance = model_cls.__new__(model_cls)
        assert instance.custom_property == "property-ok"
