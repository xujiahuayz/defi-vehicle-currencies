from __future__ import annotations

from ddvc.fetch.schema_inventory import inventory_entity, inventory_query_roots, inventory_reachable_types, type_identity


def _reference(kind: str, name: str | None = None, nested: dict | None = None) -> dict:
    return {"kind": kind, "name": name, "ofType": nested}


class FakeClient:
    def query(self, query: str, variables: dict) -> dict:
        if "__schema" in query:
            return {
                "__schema": {
                    "queryType": {
                        "fields": [
                            {
                                "name": "swaps",
                                "args": [{"name": "first", "type": _reference("SCALAR", "Int")}],
                                "type": _reference(
                                    "NON_NULL",
                                    nested=_reference(
                                        "LIST",
                                        nested=_reference("OBJECT", "Swap"),
                                    ),
                                ),
                            }
                        ]
                    }
                }
            }
        fields = {
            "Swap": [
                {"name": "id", "type": _reference("SCALAR", "ID"), "isDeprecated": False, "deprecationReason": None},
                {"name": "amount", "type": _reference("SCALAR", "BigDecimal"), "isDeprecated": False, "deprecationReason": None},
                {"name": "old", "type": _reference("SCALAR", "String"), "isDeprecated": True, "deprecationReason": "old"},
                {"name": "token", "type": _reference("OBJECT", "Token"), "isDeprecated": False, "deprecationReason": None},
                {"name": "children", "type": _reference("LIST", nested=_reference("OBJECT", "Child")), "isDeprecated": False, "deprecationReason": None},
            ],
            "Token": [
                {"name": "id", "type": _reference("SCALAR", "ID"), "isDeprecated": False, "deprecationReason": None},
                {"name": "symbol", "type": _reference("SCALAR", "String"), "isDeprecated": False, "deprecationReason": None},
            ],
            "Child": [
                {"name": "id", "type": _reference("SCALAR", "ID"), "isDeprecated": False, "deprecationReason": None},
            ],
        }
        return {"__type": {"name": variables["name"], "kind": "OBJECT", "fields": fields[variables["name"]]}}


def test_type_identity_unwraps_list_and_nonnull() -> None:
    identity = type_identity(
        _reference("NON_NULL", nested=_reference("LIST", nested=_reference("OBJECT", "Swap")))
    )
    assert identity.name == "Swap"
    assert identity.kind == "OBJECT"
    assert identity.list_valued


def test_inventory_separates_singular_and_multiplying_unselected_fields() -> None:
    result = inventory_entity(
        FakeClient(),
        entity="swaps",
        selected_fields="id token { id }",
        max_depth=3,
    )
    assert result["selected_paths"] == ["id", "token.id"]
    assert result["selected_paths_absent_from_schema"] == []
    assert result["unselected_primitive_paths"] == ["amount", "token.symbol"]
    assert result["unselected_list_primitive_paths"] == ["children.id"]
    token_symbol = next(field for field in result["fields"] if field["path"] == "token.symbol")
    child_id = next(field for field in result["fields"] if field["path"] == "children.id")
    assert not token_symbol["field_list_valued"]
    assert not token_symbol["ancestor_list_valued"]
    assert not child_id["field_list_valued"]
    assert child_id["ancestor_list_valued"]


def test_reachable_type_inventory_covers_cycles_once() -> None:
    catalog = inventory_reachable_types(FakeClient(), seed_types=["Swap"])
    assert [entry["name"] for entry in catalog] == ["Child", "Swap", "Token"]
    assert next(entry for entry in catalog if entry["name"] == "Swap")["fields"][0]["name"] == "amount"


def test_query_root_inventory_is_complete_and_typed() -> None:
    roots = inventory_query_roots(FakeClient())
    assert roots == [
        {
            "name": "swaps",
            "type": "Swap",
            "kind": "OBJECT",
            "list_valued": True,
            "arguments": [
                {"name": "first", "type": "Int", "kind": "SCALAR", "list_valued": False}
            ],
        }
    ]
