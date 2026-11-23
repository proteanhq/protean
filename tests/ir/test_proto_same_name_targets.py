"""Protobuf generation with two referenced targets that share a short name.

A message defined in the same ``.proto`` file is declared under the target's
short name. Two targets from different packages with one short name, or a
target named like the file's main message, cannot both be declared there, so
the generator raises ``ValueError`` naming both FQNs instead of dropping one.
The standalone mode (no ``import_path``) is deprecated.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from protean._deprecation import ProteanDeprecationWarning, RemovedInProtean020Warning
from protean.ir.generators.protobuf import generate_proto_schema, generate_proto_schemas
from protean.ir.generators.schema_writer import write_schemas

REFERENCE_KINDS = ["value_object", "has_one", "has_many", "value_object_list", "dict"]


def _vo(fqn: str, fields: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "element_type": "VALUE_OBJECT",
        "name": fqn.rsplit(".", 1)[-1],
        "fqn": fqn,
        "fields": fields,
    }


def _ref(kind: str, target: str) -> dict[str, Any]:
    return {"kind": kind, "type": "VO", "target": target}


def _string() -> dict[str, Any]:
    return {"kind": "standard", "type": "String"}


def _integer() -> dict[str, Any]:
    return {"kind": "standard", "type": "Integer"}


def _order(fields: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "element_type": "AGGREGATE",
        "name": "Order",
        "fqn": "sales.Order",
        "fields": fields,
    }


def _addresses() -> dict[str, dict[str, Any]]:
    return {
        "billing.Address": _vo("billing.Address", {"street": _string()}),
        "shipping.Address": _vo("shipping.Address", {"dock": _integer()}),
    }


def _two_addresses(kind: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    order = _order(
        {
            "bill_to": _ref("value_object", "billing.Address"),
            "ship_to": _ref(kind, "shipping.Address"),
        }
    )
    return order, {**_addresses(), "sales.Order": order}


def _legacy_order() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    other = _vo("other.Order", {"code": _string()})
    order = _order({"legacy": _ref("value_object", "other.Order")})
    return order, {"other.Order": other, "sales.Order": order}


def _deprecations(caught: list[warnings.WarningMessage]) -> list[str]:
    return [
        str(w.message)
        for w in caught
        if issubclass(w.category, ProteanDeprecationWarning)
    ]


class TestStandaloneModeIsDeprecated:
    def test_generate_proto_schemas_warns_once_per_call(self):
        ir = {
            "clusters": {
                "sales.Order": {
                    "aggregate": _order({"code": _string()}),
                    "value_objects": {
                        "billing.Address": _vo(
                            "billing.Address", {"street": _string()}
                        ),
                    },
                }
            },
            "projections": {},
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            schemas = generate_proto_schemas(ir)

        # Two elements, one warning: the call warns, not each element.
        assert sorted(schemas) == ["billing.Address", "sales.Order"]
        messages = _deprecations(caught)
        assert len(messages) == 1
        assert all(w.category is RemovedInProtean020Warning for w in caught)
        assert "generate_proto_schemas()" in messages[0]
        assert 'write_schemas(..., fmt="protobuf")' in messages[0]

    def test_generate_proto_schema_without_import_path_warns(self):
        order, flat = _two_addresses("value_object")
        del order["fields"]["ship_to"]
        with pytest.warns(RemovedInProtean020Warning) as record:
            generate_proto_schema(order, all_elements=flat)

        assert len(record) == 1
        message = str(record[0].message)
        assert "generate_proto_schema() without import_path" in message
        assert 'write_schemas(..., fmt="protobuf")' in message
        # The warning points at the caller, not at the generator module.
        assert record[0].filename == __file__

    def test_generate_proto_schema_with_import_path_does_not_warn(self):
        order, flat = _two_addresses("value_object")
        del order["fields"]["ship_to"]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            generate_proto_schema(order, all_elements=flat, import_path=lambda _: None)

        assert _deprecations(caught) == []


class TestSameShortNameRaises:
    @pytest.mark.parametrize("kind", REFERENCE_KINDS)
    def test_two_targets_with_one_short_name(self, kind):
        order, flat = _two_addresses(kind)
        with pytest.warns(RemovedInProtean020Warning):
            with pytest.raises(ValueError) as exc:
                generate_proto_schema(order, all_elements=flat)

        message = str(exc.value)
        assert "billing.Address and shipping.Address" in message
        assert "'Address'" in message
        assert "Give them distinct names." in message

    @pytest.mark.parametrize("kind", REFERENCE_KINDS)
    def test_two_targets_with_one_short_name_nested(self, kind):
        order, flat = _two_addresses(kind)
        with pytest.raises(ValueError, match="billing.Address and shipping.Address"):
            generate_proto_schema(order, all_elements=flat, import_path=lambda _: None)

    def test_target_named_like_the_main_message(self):
        order, flat = _legacy_order()
        with pytest.warns(RemovedInProtean020Warning):
            with pytest.raises(ValueError, match="other.Order and sales.Order"):
                generate_proto_schema(order, all_elements=flat)

    def test_target_named_like_the_main_message_nested(self):
        order, flat = _legacy_order()
        with pytest.raises(ValueError, match="other.Order and sales.Order"):
            generate_proto_schema(order, all_elements=flat, import_path=lambda _: None)

    def test_target_named_like_a_main_message_without_fqn(self):
        order = {
            "element_type": "AGGREGATE",
            "name": "Order",
            "fields": {"legacy": _ref("value_object", "other.Order")},
        }
        with pytest.warns(RemovedInProtean020Warning):
            text = generate_proto_schema(order)
        # With no fqn the element is matched by name, so this is a self-reference.
        assert "  optional Order legacy = 1;" in text

    def test_transitive_target_with_a_taken_short_name(self):
        # zone.Spot refers to other.Address, and the file already declares
        # billing.Address under the same name, so the two collide one level down.
        flat = _addresses()
        flat["zone.Spot"] = _vo(
            "zone.Spot", {"where": _ref("value_object", "other.Address")}
        )
        flat["other.Address"] = _vo("other.Address", {"line": _string()})
        order = _order(
            {
                "bill_to": _ref("value_object", "billing.Address"),
                "spot": _ref("value_object", "zone.Spot"),
            }
        )
        with pytest.warns(RemovedInProtean020Warning):
            with pytest.raises(ValueError, match="billing.Address and other.Address"):
                generate_proto_schema(order, all_elements=flat)

    def test_generate_proto_schemas_raises_for_the_colliding_element(self):
        order, _ = _two_addresses("has_one")
        ir = {
            "clusters": {
                "sales.Order": {
                    "aggregate": order,
                    "value_objects": _addresses(),
                }
            },
            "projections": {},
        }
        with pytest.warns(RemovedInProtean020Warning):
            with pytest.raises(
                ValueError, match="billing.Address and shipping.Address"
            ):
                generate_proto_schemas(ir)


class TestImportModeIsUnchanged:
    def test_targets_with_files_keep_their_full_names(self):
        order, flat = _two_addresses("dict")
        paths = {
            "billing.Address": "Billing/value_objects/Address.v1.proto",
            "shipping.Address": "Shipping/value_objects/Address.v1.proto",
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            text = generate_proto_schema(
                order, all_elements=flat, import_path=paths.get
            )

        assert _deprecations(caught) == []
        assert text == (
            'syntax = "proto3";\n'
            "package sales;\n"
            'import "Billing/value_objects/Address.v1.proto";\n'
            'import "Shipping/value_objects/Address.v1.proto";\n'
            "\n"
            "message Order {\n"
            "  optional .billing.Address bill_to = 1;\n"
            "  map<string, .shipping.Address> ship_to = 2;\n"
            "}\n"
        )

    def test_write_schemas_does_not_warn(self, tmp_path):
        ir = {
            "clusters": {
                "sales.Order": {
                    "aggregate": _order(
                        {"bill_to": _ref("value_object", "billing.Address")}
                    ),
                    "value_objects": {
                        "billing.Address": _vo("billing.Address", {"street": _string()})
                    },
                }
            },
            "projections": {},
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            written = write_schemas(ir, tmp_path, fmt="protobuf")

        assert _deprecations(caught) == []
        order = next(p for p in written if p.name.startswith("Order."))
        assert "  optional .billing.Address bill_to = 1;" in order.read_text()


class TestNoCollision:
    def test_self_reference_by_fqn_names_the_main_message(self):
        node = _vo("app.Node", {"child": _ref("value_object", "app.Node")})
        with pytest.warns(RemovedInProtean020Warning):
            text = generate_proto_schema(node, all_elements={"app.Node": node})

        assert text == (
            'syntax = "proto3";\n'
            "package app;\n"
            "\n"
            "message Node {\n"
            "  optional Node child = 1;\n"
            "}\n"
        )

    def test_one_target_used_by_two_fields_is_declared_once(self):
        flat = _addresses()
        order = _order(
            {
                "bill_to": _ref("value_object", "billing.Address"),
                "old_bill_to": _ref("has_many", "billing.Address"),
            }
        )
        with pytest.warns(RemovedInProtean020Warning):
            text = generate_proto_schema(order, all_elements=flat)

        assert text.count("message Address {") == 1
        assert "  optional Address bill_to = 1;" in text
        assert "  repeated Address old_bill_to = 2;" in text

    def test_target_reached_directly_and_transitively_is_declared_once(self):
        spot = _vo("zone.Spot", {"at": _ref("value_object", "billing.Address")})
        flat = {**_addresses(), "zone.Spot": spot}
        order = _order(
            {
                "bill_to": _ref("value_object", "billing.Address"),
                "spot": _ref("value_object", "zone.Spot"),
            }
        )
        with pytest.warns(RemovedInProtean020Warning):
            text = generate_proto_schema(order, all_elements=flat)

        assert text.count("message Address {") == 1
        assert text.count("message Spot {") == 1

    def test_self_reference_by_fqn_names_a_main_message_with_another_name(self):
        # The main message is declared under the element's name, which here
        # differs from the short name of its fqn.
        order = {
            "element_type": "AGGREGATE",
            "name": "PurchaseOrder",
            "fqn": "sales.Order",
            "fields": {"parent": _ref("value_object", "sales.Order")},
        }
        with pytest.warns(RemovedInProtean020Warning):
            standalone = generate_proto_schema(order, all_elements={})
        nested = generate_proto_schema(
            order, all_elements={}, import_path=lambda _: None
        )

        expected = (
            'syntax = "proto3";\n'
            "package sales;\n"
            "\n"
            "message PurchaseOrder {\n"
            "  optional PurchaseOrder parent = 1;\n"
            "}\n"
        )
        assert standalone == expected
        assert nested == expected


class TestDeclaredNameCollision:
    def test_renamed_map_entry_target_clashes_with_another_target(self):
        # x.LedgerEntry is nested under LedgerEntry_ to clear the hidden entry
        # message of the ``ledger`` map, which is the name y.LedgerEntry_ has.
        order = _order(
            {
                "ledger": _ref("dict", "x.LedgerEntry"),
                "z": _ref("value_object", "y.LedgerEntry_"),
            }
        )
        flat = {
            "x.LedgerEntry": _vo("x.LedgerEntry", {"amount": _integer()}),
            "sales.Order": order,
        }
        with pytest.raises(ValueError) as exc:
            generate_proto_schema(order, all_elements=flat, import_path=lambda _: None)

        message = str(exc.value)
        assert "x.LedgerEntry and y.LedgerEntry_" in message
        assert "'LedgerEntry_'" in message

    def test_write_schemas_raises_for_nested_cycle_members_with_one_name(
        self, tmp_path
    ):
        # Each Address refers to the other, so neither file may import the
        # other and each nests the other's Address inside its own.
        ir = {
            "clusters": {
                "billing.Invoice": {
                    "aggregate": {
                        "element_type": "AGGREGATE",
                        "name": "Invoice",
                        "fqn": "billing.Invoice",
                        "fields": {"code": _string()},
                    },
                    "value_objects": {
                        "billing.Address": _vo(
                            "billing.Address",
                            {"peer": _ref("value_object", "shipping.Address")},
                        ),
                    },
                },
                "shipping.Parcel": {
                    "aggregate": {
                        "element_type": "AGGREGATE",
                        "name": "Parcel",
                        "fqn": "shipping.Parcel",
                        "fields": {"code": _string()},
                    },
                    "value_objects": {
                        "shipping.Address": _vo(
                            "shipping.Address",
                            {"peer": _ref("value_object", "billing.Address")},
                        ),
                    },
                },
            },
            "projections": {},
        }
        with pytest.raises(ValueError, match="billing.Address and shipping.Address"):
            write_schemas(ir, tmp_path, fmt="protobuf")
