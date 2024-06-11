import random
import re
import time

from protean import Domain, BaseAggregate
from protean.fields import Auto


def gen_ids(prefix="id"):
    timestamp = int(time.time() * 1000)  # Milliseconds since epoch
    return f"{prefix}-{timestamp}-{random.randint(0, 1000)}"


def test_domain_accepts_custom_identity_function():
    domain = Domain(__file__, identity_function=gen_ids)

    assert domain._identity_function == gen_ids

    pattern = r"^id-\d{13}-\d+$"
    id_value = domain._identity_function()
    assert bool(re.match(pattern, id_value)) is True


def test_domain_identity_function_can_be_specified_with_lambda():
    domain = Domain(__file__, identity_function=lambda: gen_ids("foo"))

    pattern = r"^foo-\d{13}-\d+$"
    id_value = domain._identity_function()
    assert bool(re.match(pattern, id_value)) is True


def test_domain_identity_function_is_used_to_generate_identity():
    domain = Domain(__file__, identity_function=gen_ids)
    domain.config["identity_strategy"] = "function"

    class TestAggregate(BaseAggregate):
        pass

    domain.register(TestAggregate)
    domain.init(traverse=False)

    with domain.domain_context():
        aggregate = TestAggregate()
        assert aggregate.id is not None
        assert bool(re.match(r"^id-\d{13}-\d+$", aggregate.id)) is True


def test_domain_identity_function__with_params_is_used_to_generate_identity():
    domain = Domain(__file__, identity_function=lambda: gen_ids("foo"))
    domain.config["identity_strategy"] = "function"

    class TestAggregate(BaseAggregate):
        pass

    domain.register(TestAggregate)
    domain.init(traverse=False)

    with domain.domain_context():
        aggregate = TestAggregate()
        assert aggregate.id is not None
        assert bool(re.match(r"^foo-\d{13}-\d+$", aggregate.id)) is True


def test_domain_identity_function_is_used_with_explicit_auto_field():
    domain = Domain(__file__, identity_function=gen_ids)
    domain.config["identity_strategy"] = "function"

    class TestAggregate(BaseAggregate):
        aggregate_id = Auto(identifier=True)

    domain.register(TestAggregate)
    domain.init(traverse=False)

    with domain.domain_context():
        aggregate = TestAggregate()
        assert aggregate.aggregate_id is not None
        assert bool(re.match(r"^id-\d{13}-\d+$", aggregate.aggregate_id)) is True

        aggregate2 = TestAggregate(aggregate_id="foo")
        assert aggregate2.aggregate_id is not None
        assert aggregate2.aggregate_id == "foo"
