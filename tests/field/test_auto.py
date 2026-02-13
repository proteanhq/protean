import random
import re
import time
from uuid import UUID

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.projection import BaseProjection
from protean.fields import Auto
from tests.shared import assert_int_is_uuid, assert_str_is_uuid


class TestValueGeneration:
    def test_automatic_uuid_generation_of_identity_field(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field = Auto(identifier=True)

        test_domain.register(AutoTest)

        auto = AutoTest()

        assert isinstance(auto.auto_field, str)
        assert_str_is_uuid(str(auto.auto_field))
        assert auto.to_dict() == {"_version": -1, "auto_field": str(auto.auto_field)}

    def test_automatic_uuid_generation_of_non_identifier_fields(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field1 = Auto()
            auto_field2 = Auto()

        test_domain.register(AutoTest)

        auto = AutoTest()

        assert_str_is_uuid(str(auto.auto_field1))
        assert_str_is_uuid(str(auto.auto_field2))

        assert auto.to_dict() == {
            "_version": -1,
            "id": str(auto.id),
            "auto_field1": str(auto.auto_field1),
            "auto_field2": str(auto.auto_field2),
        }

    def test_automatic_incrementing_of_identifier_field(self, test_domain):
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

    def test_automatic_incrementing_of_non_identifier_fields(self, test_domain):
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

    def test_automatic_uuid_generation_of_identifier_fields_in_projections(
        self, test_domain
    ):
        class AutoTest(BaseProjection):
            auto_field1 = Auto(identifier=True)

        test_domain.register(AutoTest)

        auto = AutoTest()

        assert_str_is_uuid(str(auto.auto_field1))

        assert auto.to_dict() == {
            "auto_field1": str(auto.auto_field1),
        }

    def test_automatic_uuid_generation_of_non_identifier_fields_in_projections(
        self, test_domain
    ):
        class AutoTest(BaseProjection):
            identifier = Auto(identifier=True)
            auto_field1 = Auto()

        test_domain.register(AutoTest)

        auto = AutoTest()

        assert_str_is_uuid(str(auto.auto_field1))

        assert auto.to_dict() == {
            "identifier": str(auto.identifier),
            "auto_field1": str(auto.auto_field1),
        }

    def test_specifying_explicit_values_for_auto_field(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field = Auto(identifier=True)

        test_domain.register(AutoTest)

        uuid1 = "123e4567-e89b-12d3-a456-426614174000"
        auto1 = AutoTest(auto_field=uuid1)
        assert auto1.auto_field == uuid1


class TestCustomIdentityType:
    def test_default_identity_type(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field = Auto(identifier=True)

        test_domain.register(AutoTest)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, str)
            assert_str_is_uuid(auto.auto_field)

    def test_str_identity_type(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field = Auto(identifier=True, identity_type="string")

        test_domain.register(AutoTest)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, str)
            assert_str_is_uuid(auto.auto_field)

    def test_integer_identity_type(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field = Auto(identifier=True, identity_type="integer")

        test_domain.register(AutoTest)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, int)
            assert_int_is_uuid(auto.auto_field)

    def test_uuid_identity_type(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field = Auto(identifier=True, identity_type="uuid")

        test_domain.register(AutoTest)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, UUID)
            assert auto.auto_field.version == 4


class TestCustomIdentityStrategy:
    def gen_ids() -> str:
        timestamp = int(time.time() * 1000)  # Milliseconds since epoch
        return f"id-{timestamp}-{random.randint(0, 1000)}"

    def gen_ids2() -> str:
        timestamp = int(time.time() * 1000)  # Milliseconds since epoch
        return f"foo-{timestamp}-{random.randint(0, 1000)}"

    def gen_ids3() -> int:
        return int(time.time() * 1000)

    @pytest.fixture(autouse=True)
    def customized_domain(self, test_domain):
        test_domain.config["identity_strategy"] = "function"
        test_domain._identity_function = TestCustomIdentityStrategy.gen_ids
        return test_domain

    def test_function_identity_strategy_with_default_domain_identity_function(
        self, customized_domain
    ):
        class AutoTest(BaseAggregate):
            auto_field = Auto(identifier=True, identity_strategy="function")

        customized_domain.register(AutoTest)
        customized_domain.init(traverse=False)

        with customized_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, str)
            assert bool(re.match(r"^id-\d{13}-\d+$", auto.auto_field)) is True

    def test_custom_identity_strategy_with_lambda(self, customized_domain):
        class AutoTest(BaseAggregate):
            auto_field = Auto(
                identifier=True,
                identity_strategy="function",
                identity_function=TestCustomIdentityStrategy.gen_ids2,
            )

        customized_domain.register(AutoTest)
        customized_domain.init(traverse=False)

        with customized_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, str)
            assert bool(re.match(r"^foo-\d{13}-\d+$", auto.auto_field)) is True

    def test_function_identity_strategy_with_custom_identity_type_and_custom_function(
        self, customized_domain
    ):
        class AutoTest(BaseAggregate):
            auto_field = Auto(
                identifier=True,
                identity_strategy="function",
                identity_function=TestCustomIdentityStrategy.gen_ids3,
                identity_type="integer",
            )

        customized_domain.register(AutoTest)
        customized_domain.init(traverse=False)

        with customized_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, int)
