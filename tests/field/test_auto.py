import random
import re
import time
from uuid import UUID

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.fields import Auto, String
from tests.shared import assert_int_is_uuid, assert_str_is_uuid


class TestValueGeneration:
    def test_automatic_uuid_generation_of_identity_field(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field: Auto(identifier=True)

        test_domain.register(AutoTest)

        auto = AutoTest()

        assert isinstance(auto.auto_field, str)
        assert_str_is_uuid(str(auto.auto_field))
        assert auto.to_dict() == {"_version": -1, "auto_field": str(auto.auto_field)}

    def test_automatic_uuid_generation_of_non_identifier_fields(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field1: Auto()
            auto_field2: Auto()

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
            auto_field: Auto(identifier=True, increment=True)

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
            auto_field: Auto(increment=True)

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
            auto_field1: Auto(identifier=True)

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
            identifier: Auto(identifier=True)
            auto_field1: Auto()

        test_domain.register(AutoTest)

        auto = AutoTest()

        assert_str_is_uuid(str(auto.auto_field1))

        assert auto.to_dict() == {
            "identifier": str(auto.identifier),
            "auto_field1": str(auto.auto_field1),
        }

    def test_specifying_explicit_values_for_auto_field(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field: Auto(identifier=True)

        test_domain.register(AutoTest)

        uuid1 = "123e4567-e89b-12d3-a456-426614174000"
        auto1 = AutoTest(auto_field=uuid1)
        assert auto1.auto_field == uuid1


class TestCustomIdentityType:
    def test_default_identity_type(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field: Auto(identifier=True)

        test_domain.register(AutoTest)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, str)
            assert_str_is_uuid(auto.auto_field)

    def test_str_identity_type(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field: Auto(identifier=True, identity_type="string")

        test_domain.register(AutoTest)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, str)
            assert_str_is_uuid(auto.auto_field)

    def test_integer_identity_type(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field: Auto(identifier=True, identity_type="integer")

        test_domain.register(AutoTest)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            auto = AutoTest()

            # identity_type="integer" generates uuid4().int but the field's
            # python_type is str, so validate_default coerces it to a
            # string representation — consistent with DB-loaded values.
            assert isinstance(auto.auto_field, str)
            assert_int_is_uuid(int(auto.auto_field))

    def test_uuid_identity_type(self, test_domain):
        class AutoTest(BaseAggregate):
            auto_field: Auto(identifier=True, identity_type="uuid")

        test_domain.register(AutoTest)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            auto = AutoTest()

            # identity_type="uuid" generates a UUID but the field's
            # python_type is str, so validate_default coerces it to
            # a string representation — consistent with DB-loaded values.
            assert isinstance(auto.auto_field, str)
            assert UUID(auto.auto_field).version == 4


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
            auto_field: Auto(identifier=True, identity_strategy="function")

        customized_domain.register(AutoTest)
        customized_domain.init(traverse=False)

        with customized_domain.domain_context():
            auto = AutoTest()

            assert isinstance(auto.auto_field, str)
            assert bool(re.match(r"^id-\d{13}-\d+$", auto.auto_field)) is True

    def test_custom_identity_strategy_with_lambda(self, customized_domain):
        class AutoTest(BaseAggregate):
            auto_field: Auto(
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
            auto_field: Auto(
                identifier=True,
                identity_strategy="function",
                identity_function=TestCustomIdentityStrategy.gen_ids3,
                identity_type="integer",
            )

        customized_domain.register(AutoTest)
        customized_domain.init(traverse=False)

        with customized_domain.domain_context():
            auto = AutoTest()

            # The custom function returns int, but the field's python_type
            # is str, so validate_default coerces it to str.
            assert isinstance(auto.auto_field, str)
            assert int(auto.auto_field) > 0


class TestIdentityCoercionConsistency:
    """Tests that identity fields are consistently typed (str) whether
    created in-memory or loaded from the database.  Covers the
    validate_default=True fix on FieldSpec."""

    def test_default_identity_type_is_str(self, test_domain):
        """Default identity type (string) should produce str id."""

        class DefaultIdAggregate(BaseAggregate):
            name: String()

        test_domain.register(DefaultIdAggregate)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            agg = DefaultIdAggregate(name="test")
            assert isinstance(agg.id, str)

    def test_uuid_identity_type_coerced_to_str(self, test_domain):
        """identity_type='uuid' should generate UUID but coerce to str."""

        class UuidAggregate(BaseAggregate):
            auto_id: Auto(identifier=True, identity_type="uuid")

        test_domain.register(UuidAggregate)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            agg = UuidAggregate()
            assert isinstance(agg.auto_id, str)
            parsed = UUID(agg.auto_id)
            assert parsed.version == 4

    def test_string_identity_type_is_str(self, test_domain):
        """identity_type='string' should produce str id."""

        class StrAggregate(BaseAggregate):
            auto_id: Auto(identifier=True, identity_type="string")

        test_domain.register(StrAggregate)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            agg = StrAggregate()
            assert isinstance(agg.auto_id, str)

    def test_explicit_uuid_value_coerced_to_str(self, test_domain):
        """Passing a UUID object explicitly should also be coerced to str."""
        from uuid import uuid4

        class CoerceAggregate(BaseAggregate):
            auto_id: Auto(identifier=True)

        test_domain.register(CoerceAggregate)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            uuid_val = uuid4()
            agg = CoerceAggregate(auto_id=uuid_val)
            assert isinstance(agg.auto_id, str)
            assert agg.auto_id == str(uuid_val)


class TestIdentityConsistencyAcrossPersistence:
    """Tests that identity is consistently str both in-memory and from DB
    (uses the default memory provider, no external DB needed)."""

    def test_identity_type_consistent_after_round_trip(self, test_domain):
        """id should have the same type whether created in-memory or loaded
        from the database."""

        class RoundTripAggregate(BaseAggregate):
            name: String()

        test_domain.register(RoundTripAggregate)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            agg = RoundTripAggregate(name="test")
            original_id = agg.id
            assert isinstance(original_id, str)

            test_domain.repository_for(RoundTripAggregate).add(agg)

            loaded = test_domain.repository_for(RoundTripAggregate).get(original_id)
            assert loaded.id == original_id
            assert type(loaded.id) is type(original_id)

    def test_uuid_identity_consistent_after_round_trip(self, test_domain):
        """identity_type='uuid' should be str both in-memory and from DB."""

        class UuidRoundTrip(BaseAggregate):
            auto_id: Auto(identifier=True, identity_type="uuid")

        test_domain.register(UuidRoundTrip)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            agg = UuidRoundTrip()
            original_id = agg.auto_id
            assert isinstance(original_id, str)

            test_domain.repository_for(UuidRoundTrip).add(agg)

            loaded = test_domain.repository_for(UuidRoundTrip).get(original_id)
            assert loaded.auto_id == original_id
            assert isinstance(loaded.auto_id, str)

    def test_identity_equality_after_round_trip(self, test_domain):
        """Verify that == comparison between in-memory id and DB-loaded id
        works correctly (both are str, no UUID vs str mismatch)."""

        class EqualityAggregate(BaseAggregate):
            name: String()

        test_domain.register(EqualityAggregate)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            agg = EqualityAggregate(name="test")
            in_memory_id = agg.id

            test_domain.repository_for(EqualityAggregate).add(agg)
            loaded = test_domain.repository_for(EqualityAggregate).get(in_memory_id)

            assert loaded.id == in_memory_id
            assert type(loaded.id) is type(in_memory_id) is str
