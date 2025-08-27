import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields.basic import Integer, String
from protean.utils.reflection import attributes

from tests.shared import has_key_or_attr, get_value_from_key_or_attr


class User(BaseAggregate):
    name = String(max_length=50, referenced_as="full_name")
    age = Integer(default=21, referenced_as="years")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.init(traverse=False)


def test_attribute_name_is_field_name_when_no_referenced_as_specified():
    class BareUser(BaseAggregate):
        name = String(max_length=50)

    attrs = attributes(BareUser)
    assert "name" in attrs
    assert attrs["name"].field_name == "name"
    assert attrs["name"].referenced_as is None
    assert attrs["name"].attribute_name == "name"


def test_attribute_name_is_referenced_as_when_specified():
    attrs = attributes(User)
    assert "full_name" in attrs
    assert attrs["full_name"].field_name == "name"
    assert attrs["full_name"].referenced_as == "full_name"
    assert attrs["full_name"].attribute_name == "full_name"


def test_referenced_as_does_not_show_up_in_attrs():
    assert hasattr(User, "full_name") is False

    user = User(name="John Doe")
    assert hasattr(user, "full_name") is False


@pytest.mark.database
class TestReferencedAs:
    def test_entity_to_model_uses_referenced_as_attribute_name(self, test_domain):
        user = User(name="John Doe")
        assert user.name == "John Doe"

        user_repo = test_domain.repository_for(User)
        model_obj = user_repo._dao.database_model_cls.from_entity(user)
        assert has_key_or_attr(model_obj, "full_name") is True
        assert get_value_from_key_or_attr(model_obj, "full_name") == "John Doe"

    def test_model_to_entity_converts_referenced_as_attribute_name_to_field_name(
        self, test_domain
    ):
        user = User(name="John Doe")
        user_repo = test_domain.repository_for(User)
        model_obj = user_repo._dao.database_model_cls.from_entity(user)

        reconstructed_user = user_repo._dao.database_model_cls.to_entity(model_obj)
        assert has_key_or_attr(reconstructed_user, "name") is True
        assert has_key_or_attr(reconstructed_user, "full_name") is False
        assert get_value_from_key_or_attr(reconstructed_user, "name") == "John Doe"

    def test_query_by_field_name_with_referenced_as(self, test_domain):
        user = User(name="John Doe")
        user_repo = test_domain.repository_for(User)
        user_repo.add(user)

        hydrated_user = user_repo._dao.query.filter(name="John Doe").first
        assert hydrated_user.name == "John Doe"

    def test_query_by_attribute_name_with_referenced_as(self, test_domain):
        user = User(name="John Doe")
        user_repo = test_domain.repository_for(User)
        user_repo.add(user)

        hydrated_user = user_repo._dao.query.filter(full_name="John Doe").first
        assert hydrated_user.name == "John Doe"

    def test_different_queries_by_field_with_referenced_as(self, test_domain):
        user = User(name="John Doe")
        user_repo = test_domain.repository_for(User)
        user_repo.add(user)

        hydrated_user = user_repo._dao.query.filter(name="John Doe").first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(full_name="John Doe").first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(age=21).first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(years=21).first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(age__gt=21).first
        assert hydrated_user is None

        hydrated_user = user_repo._dao.query.filter(years__gt=21).first
        assert hydrated_user is None

        hydrated_user = user_repo._dao.query.filter(age__gte=21).first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(years__gte=21).first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(name__contains="John").first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(full_name__contains="John").first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(name__iexact="john doe").first
        assert hydrated_user.name == "John Doe"

        hydrated_user = user_repo._dao.query.filter(full_name__iexact="john doe").first
        assert hydrated_user.name == "John Doe"

    def test_order_by_referenced_as(self, test_domain):
        user1 = User(name="John Doe", age=45)
        user2 = User(name="Jane Doe", age=35)
        user3 = User(name="Jim Doe", age=12)
        user4 = User(name="Uncle Doe", age=45)
        user_repo = test_domain.repository_for(User)
        user_repo.add(user1)
        user_repo.add(user2)
        user_repo.add(user3)
        user_repo.add(user4)

        # Should work with field name
        asc_ordered_users = user_repo._dao.query.order_by("age").all().items
        assert asc_ordered_users[0].name == "Jim Doe"
        assert asc_ordered_users[1].name == "Jane Doe"
        assert asc_ordered_users[2].name in ["Uncle Doe", "John Doe"]
        assert asc_ordered_users[3].name in ["Uncle Doe", "John Doe"]

        # Should work with referenced as as well
        asc_ordered_users = user_repo._dao.query.order_by("years").all().items
        assert asc_ordered_users[0].name == "Jim Doe"
        assert asc_ordered_users[1].name == "Jane Doe"
        assert asc_ordered_users[2].name in ["Uncle Doe", "John Doe"]
        assert asc_ordered_users[3].name in ["Uncle Doe", "John Doe"]

        # Should work irrespective of asc or desc
        desc_ordered_users = user_repo._dao.query.order_by("-years").all().items
        assert desc_ordered_users[0].name in ["Uncle Doe", "John Doe"]
        assert desc_ordered_users[1].name in ["Uncle Doe", "John Doe"]
        assert desc_ordered_users[2].name == "Jane Doe"
        assert desc_ordered_users[3].name == "Jim Doe"

        # Should work with multiple fields
        asc_ordered_users = user_repo._dao.query.order_by(["age", "name"]).all().items
        assert asc_ordered_users[0].name == "Jim Doe"
        assert asc_ordered_users[1].name == "Jane Doe"
        assert asc_ordered_users[2].name in ["Uncle Doe", "John Doe"]
        assert asc_ordered_users[3].name in ["Uncle Doe", "John Doe"]

        # Should work with multiple fields in descending order
        desc_ordered_users = (
            user_repo._dao.query.order_by(["-age", "-name"]).all().items
        )
        assert desc_ordered_users[0].name in ["Uncle Doe", "John Doe"]
        assert desc_ordered_users[1].name in ["Uncle Doe", "John Doe"]
        assert desc_ordered_users[2].name == "Jane Doe"
        assert desc_ordered_users[3].name == "Jim Doe"
