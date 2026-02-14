from datetime import UTC, datetime

import pytest

from protean.exceptions import ValidationError

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

    # Pydantic's list[str] does not auto-coerce non-string values
    for kwargs in [
        {"email": "john.doe@gmail.com", "roles": [1, 2]},
        {"email": "john.doe@gmail.com", "roles": ["1", 2]},
        {"email": "john.doe@gmail.com", "roles": [1.0, 2.0]},
        {"email": "john.doe@gmail.com", "roles": [datetime.now(UTC)]},
    ]:
        with pytest.raises(ValidationError):
            ListUser(**kwargs)

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
