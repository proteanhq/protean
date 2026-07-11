"""Diagnostics: TestCommandNotImperative."""

from protean import Domain
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _assert_naming_diagnostic_shape,
)


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

    def test_imperative_commands_not_flagged(self):
        domain = Domain(name="CommandNamingClean", root_path=".")

        @domain.command(part_of="Order")
        class CreateOrder:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class PlaceOrder:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class CancelReservation:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class ProcessPayment:
            order_id = Identifier(identifier=True)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [
            d for d in ir["diagnostics"] if d["code"] == "COMMAND_NOT_IMPERATIVE"
        ]
        assert findings == []

    def test_prefix_match_is_case_insensitive(self):
        """A CapWords name (`CreateOrder`) starts with `C`, not the lowercased
        prefix `create` — so a naive case-sensitive ``startswith`` would flag it.
        Its absence from the findings proves the match lowercases both sides."""
        domain = Domain(name="CommandNamingCase", root_path=".")

        @domain.command(part_of="Order")
        class CreateOrder:
            order_id = Identifier(identifier=True)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [
            d for d in ir["diagnostics"] if d["code"] == "COMMAND_NOT_IMPERATIVE"
        ]
        assert findings == []

    def test_pinned_verbs_not_flagged(self):
        """Every verb the issue pins must pass. Guards against a membership
        drift that drops a listed verb and flags a textbook imperative command
        (e.g. `TransferFunds`, `ActivateAccount`, `ResetPassword`)."""
        domain = Domain(name="CommandNamingPinned", root_path=".")

        @domain.command(part_of="Order")
        class TransferFunds:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class ActivateAccount:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class RequestRefund:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class ResetPassword:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class MergeAccounts:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class SplitInvoice:
            order_id = Identifier(identifier=True)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [
            d for d in ir["diagnostics"] if d["code"] == "COMMAND_NOT_IMPERATIVE"
        ]
        assert findings == []

    def test_verb_prefix_requires_camelcase_boundary(self):
        """`AddressChange` lowercases to `addresschange`, a naive substring
        prefix match would see it starts with `add` and wrongly treat it as
        imperative. It must still be flagged since `Address` is not `Add`
        followed by a capitalized word."""
        domain = Domain(name="CommandNamingBoundary", root_path=".")

        @domain.command(part_of="Order")
        class AddressChange:
            order_id = Identifier(identifier=True)

        @domain.command(part_of="Order")
        class AddItem:
            order_id = Identifier(identifier=True)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [
            d for d in ir["diagnostics"] if d["code"] == "COMMAND_NOT_IMPERATIVE"
        ]
        flagged = {d["element"] for d in findings}
        assert any("AddressChange" in f for f in flagged)
        assert not any("AddItem" in f for f in flagged)
