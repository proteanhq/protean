"""Tests for the event and command catalog generator."""

from __future__ import annotations

import pytest

from protean.ir.generators.catalog import (
    _constraints_summary,
    _render_field_table,
    generate_catalog,
)


# ---------------------------------------------------------------------------
# Helpers — composable IR builders
# ---------------------------------------------------------------------------


def _field(
    kind: str = "standard",
    ftype: str = "String",
    *,
    required: bool = False,
    identifier: bool = False,
    unique: bool = False,
    max_length: int | None = None,
    min_length: int | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    choices: list[str] | None = None,
    target: str | None = None,
) -> dict:
    f: dict = {"kind": kind, "type": ftype}
    if required:
        f["required"] = True
    if identifier:
        f["identifier"] = True
    if unique:
        f["unique"] = True
    if max_length is not None:
        f["max_length"] = max_length
    if min_length is not None:
        f["min_length"] = min_length
    if min_value is not None:
        f["min_value"] = min_value
    if max_value is not None:
        f["max_value"] = max_value
    if choices is not None:
        f["choices"] = choices
    if target is not None:
        f["target"] = target
        f["kind"] = kind  # caller provides kind
    return f


def _event(
    fqn: str,
    *,
    type_str: str = "",
    version: int = 1,
    published: bool = False,
    is_fact_event: bool = False,
    fields: dict | None = None,
) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "__type__": type_str or f"Test.{name}.v{version}",
            "__version__": version,
            "element_type": "EVENT",
            "fields": fields or {},
            "fqn": fqn,
            "is_fact_event": is_fact_event,
            "name": name,
            "published": published,
        }
    }


def _command(
    fqn: str,
    *,
    type_str: str = "",
    version: int = 1,
    fields: dict | None = None,
) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "__type__": type_str or f"Test.{name}.v{version}",
            "__version__": version,
            "element_type": "COMMAND",
            "fields": fields or {},
            "fqn": fqn,
            "name": name,
        }
    }


def _cluster(
    fqn: str,
    *,
    events: dict | None = None,
    commands: dict | None = None,
) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "aggregate": {
                "element_type": "AGGREGATE",
                "fields": {},
                "fqn": fqn,
                "name": name,
                "options": {},
                "invariants": {"pre": [], "post": []},
            },
            "events": events or {},
            "commands": commands or {},
            "command_handlers": {},
            "event_handlers": {},
            "entities": {},
            "value_objects": {},
        }
    }


def _ir(
    *,
    clusters: dict | None = None,
    contracts: dict | None = None,
) -> dict:
    ir: dict = {"clusters": clusters or {}}
    if contracts is not None:
        ir["contracts"] = contracts
    return ir


# ===========================================================================
# Tests
# ===========================================================================


class TestEmptyIR:
    def test_empty_ir(self):
        result = generate_catalog({})
        assert "No clusters found" in result

    def test_empty_clusters(self):
        result = generate_catalog({"clusters": {}})
        assert "No clusters found" in result


class TestFieldTable:
    def test_empty_fields(self):
        lines = _render_field_table({})
        assert "_No fields._" in lines[0]

    def test_single_field(self):
        fields = {"name": _field(required=True)}
        lines = _render_field_table(fields)
        table_text = "\n".join(lines)
        assert "| name | String | Yes |" in table_text

    def test_multiple_fields_sorted(self):
        fields = {
            "z_field": _field(),
            "a_field": _field(required=True),
        }
        lines = _render_field_table(fields)
        table_text = "\n".join(lines)
        a_pos = table_text.index("a_field")
        z_pos = table_text.index("z_field")
        assert a_pos < z_pos

    def test_identifier_field(self):
        fields = {"id": _field("auto", "Auto", identifier=True)}
        lines = _render_field_table(fields)
        table_text = "\n".join(lines)
        assert "identifier" in table_text


class TestConstraintsSummary:
    def test_no_constraints(self):
        result = _constraints_summary(_field())
        assert result == "\u2014"

    def test_identifier(self):
        result = _constraints_summary(_field(identifier=True))
        assert "identifier" in result

    def test_unique_not_identifier(self):
        result = _constraints_summary(_field(unique=True))
        assert "unique" in result

    def test_unique_suppressed_when_identifier(self):
        result = _constraints_summary(_field(identifier=True, unique=True))
        assert "unique" not in result

    def test_max_length(self):
        result = _constraints_summary(_field(max_length=100))
        assert "max_length=100" in result

    def test_min_value(self):
        result = _constraints_summary(_field(min_value=0.0))
        assert "min_value=0.0" in result

    def test_choices(self):
        result = _constraints_summary(_field(choices=["PENDING", "CONFIRMED"]))
        assert "choices=" in result
        assert "PENDING" in result

    def test_min_length(self):
        result = _constraints_summary(_field(min_length=3))
        assert "min_length=3" in result

    def test_max_value(self):
        result = _constraints_summary(_field(max_value=999.99))
        assert "max_value=999.99" in result

    def test_multiple_constraints(self):
        result = _constraints_summary(_field(max_length=100, min_value=1))
        assert "max_length=100" in result
        assert "min_value=1" in result


class TestEventRendering:
    def test_event_heading(self):
        evts = _event("app.OrderPlaced")
        ir = _ir(clusters=_cluster("app.Order", events=evts))
        result = generate_catalog(ir)
        assert "#### OrderPlaced" in result

    def test_event_type_string(self):
        evts = _event("app.OrderPlaced", type_str="Test.OrderPlaced.v1")
        ir = _ir(clusters=_cluster("app.Order", events=evts))
        result = generate_catalog(ir)
        assert "`Test.OrderPlaced.v1`" in result

    def test_event_version(self):
        evts = _event("app.OrderPlaced", version=2)
        ir = _ir(clusters=_cluster("app.Order", events=evts))
        result = generate_catalog(ir)
        assert "**Version**: 2" in result

    def test_event_published_flag(self):
        evts = _event("app.OrderPlaced", published=True)
        ir = _ir(clusters=_cluster("app.Order", events=evts))
        result = generate_catalog(ir)
        assert "**Published**: Yes" in result

    def test_event_not_published(self):
        evts = _event("app.OrderPlaced", published=False)
        ir = _ir(clusters=_cluster("app.Order", events=evts))
        result = generate_catalog(ir)
        assert "**Published**: No" in result

    def test_fact_event_flag(self):
        evts = _event("app.OrderFact", is_fact_event=True)
        ir = _ir(clusters=_cluster("app.Order", events=evts))
        result = generate_catalog(ir)
        assert "**Fact Event**: Yes" in result

    def test_event_fields_table(self):
        evts = _event(
            "app.OrderPlaced",
            fields={
                "order_id": _field("identifier", "Identifier", required=True),
                "total": _field(required=True, ftype="Float"),
            },
        )
        ir = _ir(clusters=_cluster("app.Order", events=evts))
        result = generate_catalog(ir)
        assert "| order_id |" in result
        assert "| total |" in result

    def test_event_no_fields(self):
        evts = _event("app.EmptyEvent")
        ir = _ir(clusters=_cluster("app.Order", events=evts))
        result = generate_catalog(ir)
        assert "_No fields._" in result


class TestCommandRendering:
    def test_command_heading(self):
        cmds = _command("app.PlaceOrder")
        ir = _ir(clusters=_cluster("app.Order", commands=cmds))
        result = generate_catalog(ir)
        assert "#### PlaceOrder" in result

    def test_command_type_string(self):
        cmds = _command("app.PlaceOrder", type_str="Test.PlaceOrder.v1")
        ir = _ir(clusters=_cluster("app.Order", commands=cmds))
        result = generate_catalog(ir)
        assert "`Test.PlaceOrder.v1`" in result

    def test_command_version(self):
        cmds = _command("app.PlaceOrder", version=3)
        ir = _ir(clusters=_cluster("app.Order", commands=cmds))
        result = generate_catalog(ir)
        assert "**Version**: 3" in result

    def test_command_no_published_flag(self):
        """Commands should not show published/fact-event flags."""
        cmds = _command("app.PlaceOrder")
        ir = _ir(clusters=_cluster("app.Order", commands=cmds))
        result = generate_catalog(ir)
        assert "Published" not in result
        assert "Fact Event" not in result

    def test_command_fields_table(self):
        cmds = _command(
            "app.PlaceOrder",
            fields={
                "customer_name": _field(required=True, max_length=100),
            },
        )
        ir = _ir(clusters=_cluster("app.Order", commands=cmds))
        result = generate_catalog(ir)
        assert "| customer_name |" in result
        assert "max_length=100" in result


class TestClusterGrouping:
    def test_cluster_heading(self):
        ir = _ir(
            clusters=_cluster(
                "app.Order",
                events=_event("app.OrderPlaced"),
            )
        )
        result = generate_catalog(ir)
        assert "## Order (`app.Order`)" in result

    def test_events_section_heading(self):
        ir = _ir(
            clusters=_cluster(
                "app.Order",
                events=_event("app.OrderPlaced"),
            )
        )
        result = generate_catalog(ir)
        assert "### Events" in result

    def test_commands_section_heading(self):
        ir = _ir(
            clusters=_cluster(
                "app.Order",
                commands=_command("app.PlaceOrder"),
            )
        )
        result = generate_catalog(ir)
        assert "### Commands" in result

    def test_no_events_section_when_none(self):
        ir = _ir(
            clusters=_cluster(
                "app.Order",
                commands=_command("app.PlaceOrder"),
            )
        )
        result = generate_catalog(ir)
        assert "### Events" not in result

    def test_no_commands_section_when_none(self):
        ir = _ir(
            clusters=_cluster(
                "app.Order",
                events=_event("app.OrderPlaced"),
            )
        )
        result = generate_catalog(ir)
        assert "### Commands" not in result

    def test_multiple_clusters(self):
        clusters = {
            **_cluster("app.Order", events=_event("app.OrderPlaced")),
            **_cluster("app.Payment", events=_event("app.PaymentConfirmed")),
        }
        ir = _ir(clusters=clusters)
        result = generate_catalog(ir)
        assert "## Order" in result
        assert "## Payment" in result


class TestContractSummary:
    def test_contracts_table(self):
        evts = _event("app.OrderPlaced", published=True)
        contracts = {
            "events": [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "Test.OrderPlaced.v1",
                    "version": 1,
                }
            ]
        }
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            contracts=contracts,
        )
        result = generate_catalog(ir)
        assert "## Published Event Contracts" in result
        assert "| OrderPlaced |" in result
        assert "`Test.OrderPlaced.v1`" in result

    def test_multiple_contracts_sorted(self):
        contracts = {
            "events": [
                {"fqn": "app.PaymentConfirmed", "type": "T.PC.v1", "version": 1},
                {"fqn": "app.OrderPlaced", "type": "T.OP.v1", "version": 1},
            ]
        }
        ir = _ir(
            clusters=_cluster("app.Order"),
            contracts=contracts,
        )
        result = generate_catalog(ir)
        op_pos = result.index("OrderPlaced")
        pc_pos = result.index("PaymentConfirmed")
        assert op_pos < pc_pos

    def test_no_contracts_no_section(self):
        ir = _ir(clusters=_cluster("app.Order"))
        result = generate_catalog(ir)
        assert "Published Event Contracts" not in result

    def test_empty_contracts_list_no_section(self):
        ir = _ir(
            clusters=_cluster("app.Order"),
            contracts={"events": []},
        )
        result = generate_catalog(ir)
        assert "Published Event Contracts" not in result

    def test_separator_before_contracts(self):
        contracts = {
            "events": [{"fqn": "app.OrderPlaced", "type": "T.OP.v1", "version": 1}]
        }
        ir = _ir(
            clusters=_cluster("app.Order", events=_event("app.OrderPlaced")),
            contracts=contracts,
        )
        result = generate_catalog(ir)
        assert "---" in result


class TestFullIntegration:
    """Integration test with the ordering-style IR."""

    @pytest.fixture()
    def full_ir(self) -> dict:
        order_evts = {
            **_event(
                "app.OrderPlaced",
                type_str="Ordering.OrderPlaced.v1",
                published=True,
                fields={
                    "order_id": _field("identifier", "Identifier", required=True),
                    "customer_name": _field(required=True, max_length=100),
                    "total_amount": _field(required=True, ftype="Float"),
                },
            ),
            **_event(
                "app.OrderCancelled",
                type_str="Ordering.OrderCancelled.v1",
                published=True,
                fields={
                    "order_id": _field("identifier", "Identifier", required=True),
                    "reason": _field(),
                },
            ),
        }
        order_cmds = {
            **_command(
                "app.PlaceOrder",
                type_str="Ordering.PlaceOrder.v1",
                fields={
                    "customer_name": _field(required=True, max_length=100),
                    "items": _field("list", "List", required=True),
                },
            ),
            **_command(
                "app.CancelOrder",
                type_str="Ordering.CancelOrder.v1",
                fields={
                    "order_id": _field("identifier", "Identifier", required=True),
                    "reason": _field(max_length=500),
                },
            ),
        }
        payment_evts = _event(
            "app.PaymentConfirmed",
            type_str="Ordering.PaymentConfirmed.v1",
            published=True,
            fields={
                "order_id": _field("identifier", "Identifier", required=True),
                "amount": _field(required=True, ftype="Float"),
            },
        )
        payment_cmds = _command(
            "app.ConfirmPayment",
            type_str="Ordering.ConfirmPayment.v1",
            fields={
                "order_id": _field("identifier", "Identifier", required=True),
                "amount": _field(required=True, ftype="Float"),
            },
        )
        clusters = {
            **_cluster("app.Order", events=order_evts, commands=order_cmds),
            **_cluster("app.Payment", events=payment_evts, commands=payment_cmds),
        }
        contracts = {
            "events": [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "Ordering.OrderPlaced.v1",
                    "version": 1,
                },
                {
                    "fqn": "app.OrderCancelled",
                    "type": "Ordering.OrderCancelled.v1",
                    "version": 1,
                },
                {
                    "fqn": "app.PaymentConfirmed",
                    "type": "Ordering.PaymentConfirmed.v1",
                    "version": 1,
                },
            ]
        }
        return _ir(clusters=clusters, contracts=contracts)

    def test_title(self, full_ir: dict):
        result = generate_catalog(full_ir)
        assert result.startswith("# Event & Command Catalog")

    def test_both_clusters(self, full_ir: dict):
        result = generate_catalog(full_ir)
        assert "## Order" in result
        assert "## Payment" in result

    def test_all_events(self, full_ir: dict):
        result = generate_catalog(full_ir)
        assert "OrderPlaced" in result
        assert "OrderCancelled" in result
        assert "PaymentConfirmed" in result

    def test_all_commands(self, full_ir: dict):
        result = generate_catalog(full_ir)
        assert "PlaceOrder" in result
        assert "CancelOrder" in result
        assert "ConfirmPayment" in result

    def test_contracts_section(self, full_ir: dict):
        result = generate_catalog(full_ir)
        assert "Published Event Contracts" in result

    def test_field_tables(self, full_ir: dict):
        result = generate_catalog(full_ir)
        # Check one field from OrderPlaced
        assert "| customer_name |" in result
        assert "| total_amount |" in result
