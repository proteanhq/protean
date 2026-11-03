"""Tests that IRBuilder records a handler's subscription options in one form.

Handler Meta accepts ``subscription_type`` and ``subscription_profile`` either
as the enum member or as its name in a string. The IR records both as the
lower-case name.
"""

import json
from typing import Any

import jsonschema
import pytest

from protean import Domain, handle
from protean.fields import Identifier, String
from protean.ir import SCHEMA_PATH, load_schema
from protean.ir.builder import IRBuilder
from protean.server.subscription.profiles import SubscriptionProfile, SubscriptionType
from protean.utils import fqn


def _build_domain(
    sub_type: Any = None,
    sub_profile: Any = None,
    custom_profiles: dict[str, Any] | None = None,
) -> tuple[Domain, list[type]]:
    """Build a domain whose four subscribing elements share the given options.

    Returns the domain and the four element classes: an event handler, a
    command handler, a projector and a process manager.
    """
    domain = Domain(name="SubscriptionNorm", root_path=".")
    if custom_profiles is not None:
        domain.config["server"]["profiles"] = custom_profiles

    options: dict[str, Any] = {}
    if sub_type is not None:
        options["subscription_type"] = sub_type
    if sub_profile is not None:
        options["subscription_profile"] = sub_profile

    @domain.aggregate
    class Ledger:
        name = String(max_length=50)

    @domain.event(part_of=Ledger)
    class LedgerOpened:
        ledger_id = Identifier(required=True)

    @domain.command(part_of=Ledger)
    class OpenLedger:
        ledger_id = Identifier(required=True)

    @domain.event_handler(part_of=Ledger, **options)
    class LedgerEventHandler:
        @handle(LedgerOpened)
        def on_opened(self, event: LedgerOpened) -> None:
            pass

    @domain.command_handler(part_of=Ledger, **options)
    class LedgerCommandHandler:
        @handle(OpenLedger)
        def open(self, command: OpenLedger) -> None:
            pass

    @domain.projection
    class LedgerView:
        ledger_id = Identifier(identifier=True)

    @domain.projector(projector_for=LedgerView, aggregates=[Ledger], **options)
    class LedgerViewProjector:
        @handle(LedgerOpened)
        def on_opened(self, event: LedgerOpened) -> None:
            pass

    @domain.process_manager(stream_categories=["ledger"], **options)
    class LedgerFlow:
        ledger_id = Identifier()

        @handle(LedgerOpened, start=True, correlate="ledger_id")
        def on_opened(self, event: LedgerOpened) -> None:
            self.ledger_id = event.ledger_id

    domain.init(traverse=False)
    return domain, [
        LedgerEventHandler,
        LedgerCommandHandler,
        LedgerViewProjector,
        LedgerFlow,
    ]


def _subscriptions(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return every element's subscription block in the IR, keyed by FQN."""
    found: dict[str, dict[str, Any]] = {}
    for cluster in ir["clusters"].values():
        for kind in ("command_handlers", "event_handlers"):
            for element_fqn, entry in cluster[kind].items():
                found[element_fqn] = entry["subscription"]
    for projection in ir["projections"].values():
        for element_fqn, entry in projection["projectors"].items():
            found[element_fqn] = entry["subscription"]
    for element_fqn, entry in ir["flows"]["process_managers"].items():
        found[element_fqn] = entry["subscription"]
    return found


def _build_subscriptions(
    sub_type: Any = None,
    sub_profile: Any = None,
    custom_profiles: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the IR and return the four elements' subscription blocks."""
    domain, elements = _build_domain(sub_type, sub_profile, custom_profiles)
    subscriptions = _subscriptions(IRBuilder(domain).build())
    assert set(subscriptions) == {fqn(cls) for cls in elements}
    return subscriptions


@pytest.mark.no_test_domain
class TestSubscriptionOptionSpelling:
    def test_string_options_are_recorded(self):
        subscriptions = _build_subscriptions("event_store", "production")

        for subscription in subscriptions.values():
            assert subscription == {
                "config": {},
                "profile": "production",
                "type": "event_store",
            }

    def test_enum_options_match_string_options(self):
        from_enums = _build_subscriptions(
            SubscriptionType.EVENT_STORE, SubscriptionProfile.PRODUCTION
        )
        from_strings = _build_subscriptions("event_store", "production")

        assert from_enums == from_strings

    def test_upper_case_type_is_lower_cased(self):
        subscriptions = _build_subscriptions(sub_type="EVENT_STORE")

        for subscription in subscriptions.values():
            assert subscription["type"] == "event_store"

    def test_unset_options_are_recorded_as_null(self):
        subscriptions = _build_subscriptions()

        for subscription in subscriptions.values():
            assert subscription == {"config": {}, "profile": None, "type": None}


@pytest.mark.no_test_domain
class TestMetaKeepsDeclaredValue:
    def test_enum_stays_an_enum(self):
        _, elements = _build_domain(sub_type=SubscriptionType.EVENT_STORE)

        for cls in elements:
            assert cls.meta_.subscription_type is SubscriptionType.EVENT_STORE

    def test_string_keeps_its_case(self):
        _, elements = _build_domain(sub_type="EVENT_STORE", sub_profile="PRODUCTION")

        for cls in elements:
            assert cls.meta_.subscription_type == "EVENT_STORE"
            assert cls.meta_.subscription_profile == "PRODUCTION"


NIGHTLY_PROFILE = {"nightly": {"inherits": "batch", "messages_per_tick": 50}}


@pytest.mark.no_test_domain
class TestCustomProfile:
    def test_custom_profile_is_recorded_and_validates(self):
        domain, _ = _build_domain(
            sub_profile="nightly", custom_profiles=NIGHTLY_PROFILE
        )
        ir = IRBuilder(domain).build()

        subscriptions = _subscriptions(ir)
        assert len(subscriptions) == 4
        for subscription in subscriptions.values():
            assert subscription["profile"] == "nightly"
        jsonschema.validate(ir, load_schema())

    def test_custom_profile_name_is_lower_cased(self):
        subscriptions = _build_subscriptions(
            sub_profile="Nightly", custom_profiles=NIGHTLY_PROFILE
        )

        for subscription in subscriptions.values():
            assert subscription["profile"] == "nightly"


def _subscription_schema(version: str) -> dict[str, Any]:
    """Return a published schema version's subscription definition."""
    path = SCHEMA_PATH.parents[1] / f"v{version}" / "schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    return {"$defs": schema["$defs"], "$ref": "#/$defs/subscription"}


@pytest.mark.no_test_domain
class TestSchemaSubscriptionRules:
    def test_unknown_type_fails_current_schema(self):
        schema = _subscription_schema("0.4.0")
        jsonschema.validate({"type": "stream", "profile": None, "config": {}}, schema)

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"type": "nightly", "profile": None, "config": {}}, schema
            )

    def test_custom_profile_fails_v030_schema(self):
        schema = _subscription_schema("0.3.0")
        jsonschema.validate({"type": None, "profile": "batch", "config": {}}, schema)

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"type": None, "profile": "nightly", "config": {}}, schema
            )
