from protean import BaseAggregate, BaseView
from protean.fields import Auto
from tests.shared import assert_str_is_uuid


def test_automatic_uuid_generation_of_identifier_field(test_domain):
    class AutoTest(BaseAggregate):
        auto_field = Auto(identifier=True)

    test_domain.register(AutoTest)

    auto = AutoTest()

    assert isinstance(auto.auto_field, str)
    assert_str_is_uuid(str(auto.auto_field))
    assert auto.to_dict() == {"auto_field": str(auto.auto_field)}


def test_automatic_uuid_generation_of_non_identifier_fields(test_domain):
    class AutoTest(BaseAggregate):
        auto_field1 = Auto()
        auto_field2 = Auto()

    test_domain.register(AutoTest)

    auto = AutoTest()

    assert_str_is_uuid(str(auto.auto_field1))
    assert_str_is_uuid(str(auto.auto_field2))

    assert auto.to_dict() == {
        "id": str(auto.id),
        "auto_field1": str(auto.auto_field1),
        "auto_field2": str(auto.auto_field2),
    }


def test_automatic_incrementing_of_identifier_field(test_domain):
    class AutoTest(BaseAggregate):
        auto_field = Auto(identifier=True, increment=True)

    test_domain.register(AutoTest)

    auto1 = AutoTest()
    assert auto1.auto_field is None  # Ensure value is unset before saving
    test_domain.repository_for(AutoTest).add(auto1)
    refreshed_auto1 = test_domain.repository_for(AutoTest)._dao.query.all().items[0]
    assert refreshed_auto1.auto_field == 1

    auto2 = AutoTest()
    test_domain.repository_for(AutoTest).add(auto2)
    # Dicts are ordered in insertion order, so we can look for the second item in the DB
    refreshed_auto2 = test_domain.repository_for(AutoTest)._dao.query.all().items[1]
    assert refreshed_auto2.auto_field == 2


def test_automatic_incrementing_of_non_identifier_fields(test_domain):
    class AutoTest(BaseAggregate):
        auto_field = Auto(increment=True)

    test_domain.register(AutoTest)

    auto1 = AutoTest()
    assert auto1.auto_field is None  # Ensure value is unset before saving
    test_domain.repository_for(AutoTest).add(auto1)
    refreshed_auto1 = test_domain.repository_for(AutoTest)._dao.query.all().items[0]
    assert refreshed_auto1.auto_field == 1

    auto2 = AutoTest()
    test_domain.repository_for(AutoTest).add(auto2)
    # Dicts are ordered in insertion order, so we can look for the second item in the DB
    refreshed_auto2 = test_domain.repository_for(AutoTest)._dao.query.all().items[1]
    assert refreshed_auto2.auto_field == 2


def test_automatic_uuid_generation_of_identifier_fields_in_views(test_domain):
    class AutoTest(BaseView):
        auto_field1 = Auto(identifier=True)

    test_domain.register(AutoTest)

    auto = AutoTest()

    assert_str_is_uuid(str(auto.auto_field1))

    assert auto.to_dict() == {
        "auto_field1": str(auto.auto_field1),
    }


def test_automatic_uuid_generation_of_non_identifier_fields_in_views(test_domain):
    class AutoTest(BaseView):
        identifier = Auto(identifier=True)
        auto_field1 = Auto()

    test_domain.register(AutoTest)

    auto = AutoTest()

    assert_str_is_uuid(str(auto.auto_field1))

    assert auto.to_dict() == {
        "identifier": str(auto.identifier),
        "auto_field1": str(auto.auto_field1),
    }
