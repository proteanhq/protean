"""Diagnostics: TestCommandNotImperative."""

import pytest

from protean import Domain
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _assert_naming_diagnostic_shape,
)

# Written out by hand, not read from ``IMPERATIVE_VERBS``, so that dropping or
# misspelling a verb in the set fails a test.
EXPECTED_IMPERATIVE_VERBS = [
    "accept",
    "activate",
    "add",
    "apply",
    "approve",
    "archive",
    "assign",
    "book",
    "cancel",
    "change",
    "charge",
    "close",
    "complete",
    "confirm",
    "convert",
    "create",
    "credit",
    "deactivate",
    "debit",
    "decline",
    "delete",
    "deliver",
    "deposit",
    "disable",
    "dispatch",
    "enable",
    "enroll",
    "escalate",
    "fail",
    "freeze",
    "generate",
    "grant",
    "hire",
    "initiate",
    "invite",
    "make",
    "mark",
    "merge",
    "notify",
    "onboard",
    "open",
    "pay",
    "place",
    "process",
    "publish",
    "reactivate",
    "record",
    "reduce",
    "refund",
    "register",
    "reject",
    "release",
    "remove",
    "rename",
    "renew",
    "reopen",
    "request",
    "reserve",
    "reset",
    "restock",
    "restore",
    "resume",
    "revoke",
    "schedule",
    "send",
    "set",
    "ship",
    "split",
    "start",
    "stop",
    "submit",
    "suspend",
    "transfer",
    "unassign",
    "update",
    "validate",
    "verify",
    "withdraw",
]


class TestCommandNotImperative:
    """Verify COMMAND_NOT_IMPERATIVE naming diagnostics."""

    def test_non_imperative_commands_flagged(self):
        domain = Domain(name="CommandNaming", root_path=".")

        @domain.command(part_of="Order")
        class OrderCreation:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class OrderCommand:
            order_id = Identifier(identifier=True)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [
            d for d in ir["diagnostics"] if d["code"] == "COMMAND_NOT_IMPERATIVE"
        ]
        assert len(findings) == 2
        flagged = {d["element"] for d in findings}
        assert any("OrderCreation" in f for f in flagged)
        assert any("OrderCommand" in f for f in flagged)
        for diag in findings:
            _assert_naming_diagnostic_shape(diag)

    @pytest.mark.parametrize(
        ("names", "expected_flagged"),
        [
            (("AddressChange", "AddItem"), {"AddressChange"}),
            (("Closeness", "Openness"), {"Closeness", "Openness"}),
        ],
        ids=["add-letters-in-a-noun", "close-and-open-letters-in-a-noun"],
    )
    def test_verb_prefix_requires_camelcase_boundary(self, names, expected_flagged):
        """A name that starts with a verb's letters but has no CamelCase
        boundary after them is still flagged. `AddressChange` lowercases to
        `addresschange`, which starts with `add`, yet `Address` is not `Add`
        followed by a capitalized word. `AddItem` has the boundary and passes.
        `Closeness` and `Openness` start with `close` and `open` and are
        flagged."""
        assert _flagged_commands(None, *names) == expected_flagged

    @pytest.mark.parametrize("verb", EXPECTED_IMPERATIVE_VERBS)
    def test_every_listed_verb_is_accepted(self, verb):
        """A command named `<Verb>Ticket` passes for every verb in the list,
        such as `CloseTicket`, `RestockTicket` or `MakeTicket`. The check
        lowercases the name before it compares, so the capital first letter
        does not get the command flagged."""
        domain = Domain(name="CommandNamingCommonVerbs", root_path=".")

        command_name = f"{verb.capitalize()}Ticket"
        command_cls = type(command_name, (), {"ticket_id": Identifier(identifier=True)})
        domain.command(part_of="Ticket")(command_cls)

        @domain.aggregate
        class Ticket:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        commands = [
            c["name"]
            for cluster in ir["clusters"].values()
            for c in cluster["commands"].values()
        ]
        assert commands == [command_name]
        findings = [
            d for d in ir["diagnostics"] if d["code"] == "COMMAND_NOT_IMPERATIVE"
        ]
        assert findings == []


def _flagged_commands(command_verbs=None, *names):
    """Build a one-aggregate domain with the named commands and return the
    names reported as ``COMMAND_NOT_IMPERATIVE``."""
    domain = Domain(name="CommandNamingProjectVerbs", root_path=".")
    if command_verbs is not None:
        domain.config["lint"]["command_verbs"] = command_verbs

    for name in names:
        command_cls = type(name, (), {"ticket_id": Identifier(identifier=True)})
        domain.command(part_of="Ticket")(command_cls)

    @domain.aggregate
    class Ticket:
        name = String(max_length=50)

    domain.init(traverse=False)
    ir = IRBuilder(domain).build()
    commands = sorted(
        c["name"]
        for cluster in ir["clusters"].values()
        for c in cluster["commands"].values()
    )
    assert commands == sorted(names)
    return {
        d["element"].rsplit(".", 1)[-1]
        for d in ir["diagnostics"]
        if d["code"] == "COMMAND_NOT_IMPERATIVE"
    }


class TestProjectCommandVerbs:
    """``[lint].command_verbs`` adds a project's own verbs to the built-in list."""

    @pytest.mark.parametrize(
        "command_verbs", [None, []], ids=["setting-absent", "empty-list"]
    )
    def test_unknown_verb_is_flagged_without_project_verbs(self, command_verbs):
        assert _flagged_commands(command_verbs, "AdjustStock") == {"AdjustStock"}

    def test_project_verb_is_matched_case_insensitively(self):
        assert _flagged_commands(["Adjust"], "AdjustStock") == set()

    def test_noun_name_is_still_flagged(self):
        assert _flagged_commands(["adjust"], "OrderCreation") == {"OrderCreation"}
        assert _flagged_commands(["void", "reconcile"], "OrderCreation") == {
            "OrderCreation"
        }

    def test_project_verb_that_prefixes_a_noun_name_accepts_it(self):
        assert _flagged_commands(["order"], "OrderCreation") == set()

    def test_project_verb_needs_a_camelcase_boundary(self):
        assert _flagged_commands(["void"], "VoidInvoice", "Voidance") == {"Voidance"}

    def test_built_in_verbs_still_pass(self):
        """A project verb is accepted alongside the built-in list."""
        assert _flagged_commands(["adjust"], "PlaceOrder", "AdjustStock") == set()
