from datetime import datetime

import pytest

from sqlalchemy import types as sa_types

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import (
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
from protean.exceptions import ValidationError
from protean.globals import current_domain


class ArrayUser(BaseAggregate):
    email = String(max_length=255, required=True, unique=True)
    roles = List()  # Defaulted to Text Content Type
    integers = List(content_type=Integer)


class IntegerArrayUser(BaseAggregate):
    email = String(max_length=255, required=True, unique=True)
    roles = List(content_type=Integer)


@pytest.mark.postgresql
def test_array_data_type_association(test_domain):
    test_domain.register(ArrayUser)

    model_cls = test_domain.get_model(ArrayUser)
    type(model_cls.roles.property.columns[0].type) == sa_types.ARRAY


@pytest.mark.postgresql
def test_basic_array_data_type_operations(test_domain):
    test_domain.register(ArrayUser)

    model_cls = test_domain.get_model(ArrayUser)

    user = ArrayUser(
        email="john.doe@gmail.com", roles=["ADMIN", "USER"], integers=[9, 10]
    )
    user_model_obj = model_cls.from_entity(user)

    user_copy = model_cls.to_entity(user_model_obj)
    assert user_copy is not None
    assert user_copy.roles == ["ADMIN", "USER"]


@pytest.mark.postgresql
def test_array_any_query(test_domain):
    test_domain.register(ArrayUser)

    dao = current_domain.get_dao(ArrayUser)

    dao.create(
        email="john.doe.12345@gmail.com", roles=["JUDGE", "ADMIN"], integers=[9, 10]
    )
    dao.create(email="john.doe.67890@gmail.com", roles=["ADMIN"], integers=[11])

    assert dao.find_by(roles__any="JUDGE").email == "john.doe.12345@gmail.com"


@pytest.mark.postgresql
def test_array_contains_query(test_domain):
    test_domain.register(ArrayUser)

    dao = current_domain.get_dao(ArrayUser)
    dao.create(
        email="john.doe.12345@gmail.com", roles=["JUDGE", "ADMIN"], integers=[9, 10]
    )
    dao.create(email="john.doe.67890@gmail.com", roles=["ADMIN"], integers=[11])

    assert dao.find_by(roles__contains=["JUDGE"]).email == "john.doe.12345@gmail.com"
    assert (
        dao.find_by(roles__contains=["JUDGE", "ADMIN"]).email
        == "john.doe.12345@gmail.com"
    )
    assert dao.find_by(integers__contains=[9]).email == "john.doe.12345@gmail.com"
    assert dao.find_by(integers__contains=[11]).email == "john.doe.67890@gmail.com"


@pytest.mark.postgresql
def test_array_overlap_query(test_domain):
    test_domain.register(ArrayUser)

    dao = current_domain.get_dao(ArrayUser)
    dao.create(
        email="john.doe.12345@gmail.com", roles=["JUDGE", "ADMIN"], integers=[9, 10]
    )
    dao.create(email="john.doe.67890@gmail.com", roles=["ADMIN"], integers=[11])

    assert len(dao.query.filter(roles__overlap=["JUDGE", "ADMIN"]).all().items) == 2


@pytest.mark.postgresql
def test_array_content_type_validation(test_domain):
    test_domain.register(ArrayUser)
    test_domain.register(IntegerArrayUser)

    for kwargs in [
        {"email": "john.doe@gmail.com", "roles": [1, 2]},
        {"email": "john.doe@gmail.com", "roles": ["1", 2]},
        {"email": "john.doe@gmail.com", "roles": [1.0, 2.0]},
        {"email": "john.doe@gmail.com", "roles": [datetime.utcnow()]},
    ]:
        with pytest.raises(ValidationError) as exception:
            ArrayUser(**kwargs)
        assert exception.value.messages["roles"][0].startswith("Invalid value")

    model_cls = test_domain.get_model(IntegerArrayUser)
    user = IntegerArrayUser(email="john.doe@gmail.com", roles=[1, 2])
    user_model_obj = model_cls.from_entity(user)

    user_copy = model_cls.to_entity(user_model_obj)
    assert user_copy is not None
    assert user_copy.roles == [1, 2]

    for kwargs in [
        {"email": "john.doe@gmail.com", "roles": ["ADMIN", "USER"]},
        {"email": "john.doe@gmail.com", "roles": ["1", "2"]},
        {"email": "john.doe@gmail.com", "roles": [datetime.utcnow()]},
    ]:
        with pytest.raises(ValidationError) as exception:
            IntegerArrayUser(**kwargs)
        assert exception.value.messages["roles"][0].startswith("Invalid value")


@pytest.mark.postgresql
def test_that_only_specific_primitive_types_are_allowed_as_content_types(test_domain):
    List(content_type=String)
    List(content_type=Identifier)
    List(content_type=Integer)
    List(content_type=Float)
    List(content_type=Boolean)
    List(content_type=Date)
    List(content_type=DateTime)

    with pytest.raises(ValidationError) as error:
        List(content_type=Auto)

    assert error.value.messages == {"content_type": ["Content type not supported"]}
