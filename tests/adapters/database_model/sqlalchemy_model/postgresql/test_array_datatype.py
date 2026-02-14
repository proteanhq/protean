from datetime import UTC, datetime

import pytest
from sqlalchemy import types as sa_types

from protean.core.aggregate import BaseAggregate
from protean.exceptions import ValidationError
from protean.utils.globals import current_domain


class ArrayUser(BaseAggregate):
    email: str
    roles: list[str] = []
    integers: list[int] = []


class IntegerArrayUser(BaseAggregate):
    email: str
    roles: list[int] = []


@pytest.mark.postgresql
def test_array_data_type_association(test_domain):
    test_domain.register(ArrayUser)

    database_model_cls = test_domain.repository_for(ArrayUser)._database_model
    type(database_model_cls.roles.property.columns[0].type) is sa_types.ARRAY


@pytest.mark.postgresql
def test_basic_array_data_type_operations(test_domain):
    test_domain.register(ArrayUser)

    database_model_cls = test_domain.repository_for(ArrayUser)._database_model

    user = ArrayUser(
        email="john.doe@gmail.com", roles=["ADMIN", "USER"], integers=[9, 10]
    )
    user_model_obj = database_model_cls.from_entity(user)

    user_copy = database_model_cls.to_entity(user_model_obj)
    assert user_copy is not None
    assert user_copy.roles == ["ADMIN", "USER"]


@pytest.mark.postgresql
def test_array_any_query(test_domain):
    test_domain.register(ArrayUser)

    dao = current_domain.repository_for(ArrayUser)._dao

    dao.create(
        email="john.doe.12345@gmail.com", roles=["JUDGE", "ADMIN"], integers=[9, 10]
    )
    dao.create(email="john.doe.67890@gmail.com", roles=["ADMIN"], integers=[11])

    assert dao.find_by(roles__any="JUDGE").email == "john.doe.12345@gmail.com"


@pytest.mark.postgresql
def test_array_contains_query(test_domain):
    test_domain.register(ArrayUser)

    dao = current_domain.repository_for(ArrayUser)._dao
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

    dao = current_domain.repository_for(ArrayUser)._dao
    dao.create(
        email="john.doe.12345@gmail.com", roles=["JUDGE", "ADMIN"], integers=[9, 10]
    )
    dao.create(email="john.doe.67890@gmail.com", roles=["ADMIN"], integers=[11])

    assert len(dao.query.filter(roles__overlap=["JUDGE", "ADMIN"]).all().items) == 2


@pytest.mark.postgresql
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
        with pytest.raises(ValidationError):
            IntegerArrayUser(**kwargs)
