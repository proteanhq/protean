"""Check what docs/reference/migration/v0-18.md says about upgrading to 0.18.

Each test loads its example fresh, so every test gets its own domain and its
own memory stores. The page's "before" code is the old API and stays inline on
the page; where the page says the old code now raises or warns, a test here
builds that code and checks the error or the warning.
"""

import logging
import re

import pytest

from protean import Domain, Index, apply
from protean._deprecation import RemovedInProtean020Warning, RemovedInProtean10Warning
from protean.exceptions import ConfigurationError, IncorrectUsageError, ValidationError
from protean.fields import Identifier, String
from protean.server.supervisor import Supervisor
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def activated(domain):
    domain.init(traverse=False)
    return domain.domain_context()


@pytest.fixture
def cache_example():
    module = load_example("reference/migration/v0-18/001.py")
    with activated(module.domain):
        yield module, module.domain.cache_for(module.UserProfile)


@pytest.fixture
def orders_example():
    module = load_example("reference/migration/v0-18/002.py")
    with activated(module.domain):
        yield module


@pytest.fixture
def validation_example():
    module = load_example("reference/migration/v0-18/006.py")
    with activated(module.domain):
        yield module


class TestMemoryCacheAbsentKey:
    def test_remove_by_key_on_an_absent_key_logs_and_does_not_raise(
        self, cache_example, caplog
    ):
        module, cache = cache_example

        with caplog.at_level(logging.INFO, logger=module.__name__):
            module.remove_cached(cache, "user_profile:::missing")

        assert "nothing cached for user_profile:::missing" in caplog.text

    def test_remove_by_key_removes_a_present_key(self, cache_example, caplog):
        module, cache = cache_example
        cache.add(module.UserProfile(user_id="u1", name="Ada"))

        with caplog.at_level(logging.INFO, logger=module.__name__):
            module.remove_cached(cache, "user_profile:::u1")

        assert "nothing cached" not in caplog.text
        assert cache.get("user_profile:::u1") is None

    def test_remove_and_set_ttl_on_an_absent_key_do_nothing(self, cache_example):
        module, cache = cache_example

        cache.remove(module.UserProfile(user_id="never-added", name="x"))
        cache.set_ttl("user_profile:::never-added", 60)

        assert cache.get("user_profile:::never-added") is None

    def test_set_ttl_still_rejects_an_invalid_ttl_on_an_absent_key(self, cache_example):
        _, cache = cache_example

        with pytest.raises(ConfigurationError, match="TTL = -1"):
            cache.set_ttl("user_profile:::never-added", -1)


class TestGetTtl:
    def test_an_absent_key_has_no_ttl(self, cache_example):
        module, cache = cache_example

        assert cache.get_ttl("user_profile:::missing") is None
        assert module.describe_ttl(cache, "user_profile:::missing") == "no such key"

    def test_a_present_key_reports_the_seconds_remaining(self, cache_example):
        module, cache = cache_example
        cache.add(module.UserProfile(user_id="u1", name="Ada"), ttl=120)

        ttl = cache.get_ttl("user_profile:::u1")

        assert 0 < ttl <= 120
        assert re.fullmatch(
            r"\d+ seconds remaining", module.describe_ttl(cache, "user_profile:::u1")
        )


class TestCacheKeyPatterns:
    def test_a_glob_selects_every_entry_in_key_order(self, cache_example):
        module, cache = cache_example
        cache.add(module.UserProfile(user_id="u2", name="Grace"))
        cache.add(module.UserProfile(user_id="u1", name="Ada"))

        profiles = module.all_user_profiles(cache)

        assert [p.user_id for p in profiles] == ["u1", "u2"]

    def test_a_regex_pattern_now_matches_a_literal_dot(self, cache_example):
        module, cache = cache_example
        cache.add(module.UserProfile(user_id="u1", name="Ada"))

        assert cache._get_all("user_profile:::.*") == []

    def test_process_all_visits_every_match(self, cache_example):
        module, cache = cache_example
        cache.add(module.UserProfile(user_id="u1", name="Ada"))
        cache.add(module.UserProfile(user_id="u2", name="Grace"))
        seen = []

        module.process_all(cache, "user_profile:::*", seen.append)

        assert [p.name for p in seen] == ["Ada", "Grace"]

    def test_the_public_get_all_is_gone(self, cache_example):
        _, cache = cache_example

        assert not hasattr(cache, "get_all")


class TestDaoUpdateDeprecation:
    def test_ship_order_applies_the_change_and_raises_the_event(self, orders_example):
        module = orders_example
        repo = module.domain.repository_for(module.Order)
        order = module.Order()
        repo.add(order)

        module.ship_order(order.id)

        assert repo.get(order.id).status == "shipped"
        events = module.domain.event_store.store.read(f"ordering::order-{order.id}")
        assert [m.metadata.headers.type for m in events] == ["Ordering.OrderShipped.v1"]

    def test_cancel_pending_orders_cancels_only_pending_ones(self, orders_example):
        module = orders_example
        repo = module.domain.repository_for(module.Order)
        pending = [module.Order(), module.Order()]
        shipped = module.Order(status="shipped")
        for order in [*pending, shipped]:
            repo.add(order)

        module.cancel_pending_orders()

        assert [repo.get(o.id).status for o in pending] == ["cancelled", "cancelled"]
        assert repo.get(shipped.id).status == "shipped"

    def test_dao_update_still_works_and_warns(self, orders_example):
        module = orders_example
        repo = module.domain.repository_for(module.Order)
        order = module.Order()
        repo.add(order)
        dao = repo._dao

        with pytest.warns(RemovedInProtean10Warning):
            dao.update(dao.get(order.id), status="shipped")

        assert repo.get(order.id).status == "shipped"

    def test_queryset_update_still_works_and_warns(self, orders_example):
        module = orders_example
        repo = module.domain.repository_for(module.Order)
        order = module.Order()
        repo.add(order)

        with pytest.warns(RemovedInProtean10Warning):
            repo._dao.query.filter(status="pending").update(status="cancelled")

        assert repo.get(order.id).status == "cancelled"


class TestSupervisorLogLevel:
    def test_log_level_replaces_debug(self, recwarn):
        module = load_example("reference/migration/v0-18/003.py")

        assert module.supervisor.log_level == "DEBUG"
        assert module.supervisor.num_workers == 4
        assert not [w for w in recwarn if w.category is RemovedInProtean020Warning]

    def test_debug_true_still_works_and_warns(self):
        with pytest.warns(RemovedInProtean020Warning):
            supervisor = Supervisor("my_package.domain", num_workers=4, debug=True)

        assert supervisor.log_level == "DEBUG"

    def test_log_level_wins_over_debug(self):
        with pytest.warns(RemovedInProtean020Warning):
            supervisor = Supervisor(
                "my_package.domain", num_workers=1, debug=True, log_level="INFO"
            )

        assert supervisor.log_level == "INFO"


class TestSanitizeDefault:
    def build(self):
        domain = Domain(name="Comments")

        @domain.aggregate
        class Comment:
            name = String(max_length=100, sanitize=True)
            body = String(max_length=100)

        domain.init(traverse=False)
        return domain, Comment

    def test_sanitize_true_escapes_and_unset_stores_raw(self):
        domain, Comment = self.build()

        with domain.domain_context():
            comment = Comment(name="<script>x</script>", body="<script>x</script>")

        assert comment.name == "&lt;script&gt;x&lt;/script&gt;"
        assert comment.body == "<script>x</script>"


class TestReservedFieldName:
    def test_the_aggregate_registers_with_the_name_reserved(self):
        module = load_example("reference/migration/v0-18/004.py")
        module.domain.init(traverse=False)

        assert tuple(module.Order.meta_.reserved) == ("note",)
        assert "note" not in module.Order.__container_fields__

    def test_replay_drops_an_assignment_to_a_reserved_name(self):
        domain = Domain(name="Ordering")

        @domain.event(part_of="Order")
        class NoteAdded:
            order_id = Identifier(identifier=True)
            note = String()

        @domain.aggregate(event_sourced=True, reserved=["note"])
        class Order:
            order_id = Identifier(identifier=True)

            @apply
            def note_added(self, event: NoteAdded):
                self.order_id = event.order_id
                self.note = event.note

        domain.init(traverse=False)

        with domain.domain_context():
            order = Order.from_events([NoteAdded(order_id="o1", note="hello")])

        assert order.order_id == "o1"
        assert not hasattr(order, "note")

    def test_replay_drops_the_helpers_of_a_reserved_association(self):
        domain = Domain(name="Ordering")
        seen = {}

        @domain.entity(part_of="Order")
        class OrderItem:
            name = String()

        @domain.event(part_of="Order")
        class ItemAdded:
            order_id = Identifier(identifier=True)
            name = String()

        @domain.aggregate(event_sourced=True, reserved=["items"])
        class Order:
            order_id = Identifier(identifier=True)

            @apply
            def item_added(self, event: ItemAdded):
                self.order_id = event.order_id
                seen["add"] = self.add_items(OrderItem(name=event.name))
                seen["remove"] = self.remove_items(OrderItem(name=event.name))
                for reader in ("get_one_from_items", "filter_items"):
                    try:
                        getattr(self, reader)(name=event.name)
                    except AttributeError as exc:
                        seen[reader] = str(exc)

        domain.init(traverse=False)

        with domain.domain_context():
            order = Order.from_events([ItemAdded(order_id="o1", name="pen")])

        assert order.order_id == "o1"
        assert seen == {
            "add": None,
            "remove": None,
            "get_one_from_items": "'Order' object has no attribute 'get_one_from_items'",
            "filter_items": "'Order' object has no attribute 'filter_items'",
        }

    def test_the_live_path_still_raises_on_a_reserved_helper(self):
        domain = Domain(name="Ordering")

        @domain.entity(part_of="Order")
        class OrderItem:
            name = String()

        @domain.aggregate(event_sourced=True, reserved=["items"])
        class Order:
            order_id = Identifier(identifier=True)

        domain.init(traverse=False)

        with domain.domain_context():
            order = Order(order_id="o1")
            with pytest.raises(AttributeError, match="add_items"):
                order.add_items(OrderItem(name="pen"))

    @pytest.mark.parametrize("name", ["", "_note"])
    def test_an_empty_or_private_reserved_name_raises(self, name):
        domain = Domain(name="Ordering")

        with pytest.raises(IncorrectUsageError, match="are not field names"):

            @domain.aggregate(event_sourced=True, reserved=[name])
            class Order:
                order_id = Identifier(identifier=True)

            domain.init(traverse=False)

    def test_reusing_a_reserved_name_raises(self):
        domain = Domain(name="Ordering")

        with pytest.raises(IncorrectUsageError, match="note"):

            @domain.aggregate(event_sourced=True, reserved=["note"])
            class Order:
                order_id = Identifier(identifier=True)
                note = String()

            domain.init(traverse=False)


class TestRawIndexDialect:
    def test_postgresql_is_accepted(self):
        module = load_example("reference/migration/v0-18/005.py")
        module.domain.init(traverse=False)

        assert module.gin_index.dialect == "postgresql"
        assert module.Outbox.meta_.indexes == [module.gin_index]

    def test_an_unknown_dialect_raises_at_init(self):
        domain = Domain(name="Messaging")

        @domain.aggregate(
            indexes=[
                Index.from_sql(
                    "postgres", "CREATE INDEX ix_data_gin ON outbox USING gin (data)"
                )
            ]
        )
        class Outbox:
            data = String()

        with pytest.raises(IncorrectUsageError, match="postgres"):
            domain.init(traverse=False)


def accepts_anything(**kwargs):
    return None


def rejects_with(message):
    def build(**kwargs):
        raise ValidationError({"items": [message]})

    return build


class TestAssertHelpersRemoved:
    """The page's replacement tests pass on the real ``Order``, and fail when
    ``Order`` accepts an empty order or rejects it for another reason."""

    @pytest.mark.parametrize(
        "name",
        ["test_an_order_needs_an_item", "test_an_order_needs_an_item_with_match"],
    )
    def test_the_assert_invalid_replacement_passes_on_the_real_order(
        self, validation_example, name
    ):
        getattr(validation_example, name)()

    @pytest.mark.parametrize(
        "name",
        ["test_an_order_needs_an_item", "test_an_order_needs_an_item_with_match"],
    )
    def test_the_assert_invalid_replacement_fails_when_nothing_raises(
        self, validation_example, monkeypatch, name
    ):
        monkeypatch.setattr(validation_example, "Order", accepts_anything)

        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            getattr(validation_example, name)()

    def test_the_assert_invalid_replacement_checks_the_message(
        self, validation_example, monkeypatch
    ):
        monkeypatch.setattr(
            validation_example, "Order", rejects_with("Customer is unknown")
        )

        with pytest.raises(AssertionError):
            validation_example.test_an_order_needs_an_item()

    def test_the_match_replacement_checks_the_message(
        self, validation_example, monkeypatch
    ):
        monkeypatch.setattr(
            validation_example, "Order", rejects_with("Customer is unknown")
        )

        with pytest.raises(AssertionError, match="at least one item"):
            validation_example.test_an_order_needs_an_item_with_match()

    def test_a_plain_call_replaces_assert_valid(self, validation_example):
        validation_example.test_an_order_with_an_item_is_valid()

    def test_the_plain_call_fails_when_the_order_is_rejected(
        self, validation_example, monkeypatch
    ):
        monkeypatch.setattr(
            validation_example, "Order", rejects_with("Order is already shipped")
        )

        with pytest.raises(ValidationError, match="already shipped"):
            validation_example.test_an_order_with_an_item_is_valid()

    def test_the_invariant_message_is_what_the_page_checks(self, validation_example):
        with pytest.raises(ValidationError) as exc_info:
            validation_example.Order(customer_id="c1", items=[])

        assert exc_info.value.messages == {
            "items": ["Order must have at least one item"]
        }

    @pytest.mark.parametrize(
        "name",
        ["assert_valid", "assert_invalid"],
    )
    def test_importing_the_old_helpers_raises(self, name):
        with pytest.raises(ImportError, match=name):
            exec(f"from protean.testing import {name}")

    def test_the_018_warning_category_is_gone(self):
        with pytest.raises(ImportError, match="RemovedInProtean018Warning"):
            from protean._deprecation import RemovedInProtean018Warning  # noqa: F401


def test_a_rejected_change_is_rolled_back(capsys):
    module = load_example("reference/migration/v0-18/007.py")

    with activated(module.domain):
        assert module.rejected_total() == 10.0

    out = capsys.readouterr().out
    assert out.startswith("rejected: ")
    assert "{'total': ['Total cannot be negative']}" in out


class TestOmittedValueObjectArgument:
    @pytest.fixture
    def example(self):
        module = load_example("reference/migration/v0-18/008.py")
        with activated(module.domain):
            yield module

    def test_an_omitted_argument_gets_the_default(self, example):
        event = example.Event(venue_street="1 Main St")

        assert event.venue.street == "1 Main St"
        assert event.venue.city == "Unknown"

    def test_passing_none_keeps_none(self, example):
        event = example.event_without_a_city()

        assert event.venue.street == "1 Main St"
        assert event.venue.city is None


class TestNonDictPositionalArgument:
    @pytest.fixture
    def example(self):
        module = load_example("reference/migration/v0-18/009.py")
        with activated(module.domain):
            yield module

    def test_keyword_arguments_override_the_dict_template(self, example):
        order = example.placed_order()

        assert order.customer_id == "c-1"
        assert order.status == "PLACED"

    def test_a_non_dict_payload_is_caught_as_type_error(self, example):
        assert example.build_order("c-1") is None
        assert example.build_order({"customer_id": "c-1"}).customer_id == "c-1"

    def test_a_non_dict_payload_raises_type_error_not_assertion_error(self, example):
        with pytest.raises(TypeError, match="must be a dict"):
            example.Order("c-1")

    def test_renamed_from_with_a_non_string_raises_type_error(self):
        with pytest.raises(TypeError, match="renamed_from"):
            String(renamed_from=42)

    def test_renamed_from_with_an_empty_alias_still_raises_value_error(self):
        with pytest.raises(ValueError, match="renamed_from"):
            String(renamed_from=[""])


class TestDatabaseModelOptionRemoved:
    def test_the_old_decorator_option_raises(self):
        domain = Domain(name="Accounts")

        with pytest.raises(ConfigurationError, match="database_model"):

            @domain.aggregate(database_model="UserModel")
            class User:
                email: String(max_length=255, required=True)

    def test_the_fix_registers_the_custom_model(self):
        module = load_example("reference/migration/v0-18/010.py")

        assert module.UserModel.meta_.part_of is module.User

        with activated(module.domain):
            model = module.domain.repository_for(module.User)._database_model

            assert issubclass(model, module.UserModel)
