from datetime import UTC, datetime

import pytest
from sqlalchemy import types as sa_types

from protean.core.aggregate import BaseAggregate
from protean.exceptions import ValidationError


class ArrayUser(BaseAggregate):
    email: str
    roles: list[str] = []


class IntegerArrayUser(BaseAggregate):
    email: str
    roles: list[int] = []


@pytest.mark.sqlite
def test_array_data_type_association(test_domain):
    test_domain.register(ArrayUser)

    database_model_cls = test_domain.repository_for(ArrayUser)._database_model
    type(database_model_cls.roles.property.columns[0].type) is sa_types.ARRAY


@pytest.mark.sqlite
def test_basic_array_data_type_operations(test_domain):
    test_domain.register(ArrayUser)

    database_model_cls = test_domain.repository_for(ArrayUser)._database_model

    user = ArrayUser(email="john.doe@gmail.com", roles=["ADMIN", "USER"])
    user_model_obj = database_model_cls.from_entity(user)

    user_copy = database_model_cls.to_entity(user_model_obj)
    assert user_copy is not None
    assert user_copy.roles == ["ADMIN", "USER"]


@pytest.mark.sqlite
def test_array_content_type_validation(test_domain):
    test_domain.register(ArrayUser)
    test_domain.register(IntegerArrayUser)

    # Pydantic's list[str] does not auto-coerce non-string values
    for kwargs in [
        {"email": "john.doe@gmail.com", "roles": [1, 2]},
        {"email": "john.doe@gmail.com", "roles": ["1", 2]},
        {"email": "john.doe@gmail.com", "roles": [1.0, 2.0]},
        {"email": "john.doe@gmail.com", "roles": [datetime.now(UTC)]},
    ]:
        with pytest.raises(ValidationError):
            ArrayUser(**kwargs)

    database_model_cls = test_domain.repository_for(IntegerArrayUser)._database_model
    user = IntegerArrayUser(email="john.doe@gmail.com", roles=[1, 2])
    user_model_obj = database_model_cls.from_entity(user)

    user_copy = database_model_cls.to_entity(user_model_obj)
    assert user_copy is not None
    assert user_copy.roles == [1, 2]

    for kwargs in [
        {"email": "john.doe@gmail.com", "roles": ["ADMIN", "USER"]},
        {"email": "john.doe@gmail.com", "roles": [datetime.now(UTC)]},
    ]:
        with pytest.raises(ValidationError) as exception:
            IntegerArrayUser(**kwargs)
        assert "roles" in exception.value.messages
