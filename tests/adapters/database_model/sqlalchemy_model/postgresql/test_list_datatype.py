from datetime import UTC, date, datetime

import pytest

from protean.exceptions import ValidationError
from protean.fields import (
    Auto,
    Boolean,
    Date,
    DateTime,
    Float,
    Identifier,
    Integer,
    List,
    String,
)

from .elements import IntegerListUser, ListUser


@pytest.mark.postgresql
def test_basic_array_data_type_support(test_domain):
    test_domain.register(ListUser)

    database_model_cls = test_domain.repository_for(ListUser)._database_model
    user = ListUser(email="john.doe@gmail.com", roles=["ADMIN", "USER"])
    user_model_obj = database_model_cls.from_entity(user)

    user_copy = database_model_cls.to_entity(user_model_obj)
    assert user_copy is not None
    assert user_copy.roles == ["ADMIN", "USER"]


@pytest.mark.postgresql
def test_array_content_type_validation(test_domain):
    test_domain.register(ListUser)
    test_domain.register(IntegerListUser)

    for kwargs in [
        {"email": "john.doe@gmail.com", "roles": [1, 2]},
        {"email": "john.doe@gmail.com", "roles": ["1", 2]},
        {"email": "john.doe@gmail.com", "roles": [1.0, 2.0]},
        {"email": "john.doe@gmail.com", "roles": [datetime.now(UTC)]},
    ]:
        try:
            ListUser(**kwargs)
        except ValidationError:
            pytest.fail("Failed to convert integers into strings in List field type")

    database_model_cls = test_domain.repository_for(IntegerListUser)._database_model
    user = IntegerListUser(email="john.doe@gmail.com", roles=[1, 2])
    user_model_obj = database_model_cls.from_entity(user)

    user_copy = database_model_cls.to_entity(user_model_obj)
    assert user_copy is not None
    assert user_copy.roles == [1, 2]

    for kwargs in [
        {"email": "john.doe@gmail.com", "roles": ["ADMIN", "USER"]},
        {"email": "john.doe@gmail.com", "roles": [datetime.now(UTC)]},
    ]:
        with pytest.raises(ValidationError) as exception:
            IntegerListUser(**kwargs)
        assert "roles" in exception.value.messages


@pytest.mark.postgresql
def test_that_only_specific_primitive_types_are_allowed_as_content_types(test_domain):
    from protean.fields.spec import FieldSpec

    string_list = List(content_type=String)
    assert isinstance(string_list, FieldSpec)
    assert string_list.python_type == list[str]

    identifier_list = List(content_type=Identifier)
    assert isinstance(identifier_list, FieldSpec)
    assert identifier_list.python_type == list[str]

    integer_list = List(content_type=Integer)
    assert isinstance(integer_list, FieldSpec)
    assert integer_list.python_type == list[int]

    float_list = List(content_type=Float)
    assert isinstance(float_list, FieldSpec)
    assert float_list.python_type == list[float]

    boolean_list = List(content_type=Boolean)
    assert isinstance(boolean_list, FieldSpec)
    assert boolean_list.python_type == list[bool]

    date_list = List(content_type=Date)
    assert isinstance(date_list, FieldSpec)
    assert date_list.python_type == list[date]

    datetime_list = List(content_type=DateTime)
    assert isinstance(datetime_list, FieldSpec)
    assert datetime_list.python_type == list[datetime]

    with pytest.raises(ValidationError) as error:
        List(content_type=Auto)

    assert error.value.messages == {"content_type": ["Content type not supported"]}
