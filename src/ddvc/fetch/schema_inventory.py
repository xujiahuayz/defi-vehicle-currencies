"""Live GraphQL schema inventory for one-pass raw-field admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ddvc.fetch.graphql_selection import selected_paths


LEAF_KINDS = frozenset({"SCALAR", "ENUM"})
TYPE_REF = "kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } } }"
QUERY_SCHEMA = f"query {{ __schema {{ queryType {{ fields {{ name args {{ name type {{ {TYPE_REF} }} }} type {{ {TYPE_REF} }} }} }} }} }}"
TYPE_SCHEMA = f"query TypeFields($name: String!) {{ __type(name: $name) {{ name kind fields(includeDeprecated: true) {{ name isDeprecated deprecationReason type {{ {TYPE_REF} }} }} }} }}"


class QueryClient(Protocol):
    def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class TypeIdentity:
    name: str
    kind: str
    list_valued: bool


def type_identity(reference: Mapping[str, Any]) -> TypeIdentity:
    """Resolve a wrapped GraphQL type and retain whether any wrapper is a list."""

    current: Mapping[str, Any] | None = reference
    list_valued = False
    while current is not None:
        kind = str(current.get("kind") or "")
        list_valued = list_valued or kind == "LIST"
        name = current.get("name")
        if isinstance(name, str) and name:
            return TypeIdentity(name=name, kind=kind, list_valued=list_valued)
        nested = current.get("ofType")
        current = nested if isinstance(nested, Mapping) else None
    raise ValueError("GraphQL type reference has no named leaf")


def query_fields(client: QueryClient) -> dict[str, dict[str, Any]]:
    payload = client.query(QUERY_SCHEMA, {})
    schema = payload.get("__schema")
    query_type = schema.get("queryType") if isinstance(schema, Mapping) else None
    fields = query_type.get("fields") if isinstance(query_type, Mapping) else None
    if not isinstance(fields, list):
        raise ValueError("GraphQL introspection lacks query fields")
    return {
        str(field["name"]): dict(field)
        for field in fields
        if isinstance(field, Mapping) and isinstance(field.get("name"), str)
    }


def inventory_query_roots(client: QueryClient) -> list[dict[str, Any]]:
    """Return every query-root field exposed by the deployment."""

    roots = []
    for name, field in sorted(query_fields(client).items()):
        reference = field.get("type")
        if not isinstance(reference, Mapping):
            continue
        identity = type_identity(reference)
        arguments = []
        for argument in field.get("args") or []:
            if not isinstance(argument, Mapping) or not isinstance(argument.get("name"), str):
                continue
            argument_reference = argument.get("type")
            if not isinstance(argument_reference, Mapping):
                continue
            argument_identity = type_identity(argument_reference)
            arguments.append(
                {
                    "name": argument["name"],
                    "type": argument_identity.name,
                    "kind": argument_identity.kind,
                    "list_valued": argument_identity.list_valued,
                }
            )
        roots.append(
            {
                "name": name,
                "type": identity.name,
                "kind": identity.kind,
                "list_valued": identity.list_valued,
                "arguments": sorted(arguments, key=lambda item: str(item["name"])),
            }
        )
    return roots


def _type_fields(client: QueryClient, name: str, cache: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if name in cache:
        return cache[name]
    payload = client.query(TYPE_SCHEMA, {"name": name})
    type_payload = payload.get("__type")
    fields = type_payload.get("fields") if isinstance(type_payload, Mapping) else None
    if not isinstance(fields, list):
        raise ValueError(f"GraphQL introspection lacks fields for type {name}")
    cache[name] = [dict(field) for field in fields if isinstance(field, Mapping)]
    return cache[name]


def _walk_fields(
    client: QueryClient,
    type_name: str,
    *,
    prefix: str,
    depth: int,
    max_depth: int,
    inherited_list: bool,
    ancestors: frozenset[str],
    cache: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in sorted(_type_fields(client, type_name, cache), key=lambda item: str(item.get("name") or "")):
        field_name = field.get("name")
        reference = field.get("type")
        if not isinstance(field_name, str) or not isinstance(reference, Mapping):
            continue
        identity = type_identity(reference)
        path = f"{prefix}.{field_name}" if prefix else field_name
        list_valued = inherited_list or identity.list_valued
        row = {
            "path": path,
            "type": identity.name,
            "kind": identity.kind,
            "field_list_valued": identity.list_valued,
            "ancestor_list_valued": inherited_list,
            "list_valued": list_valued,
            "deprecated": bool(field.get("isDeprecated", False)),
            "deprecation_reason": field.get("deprecationReason"),
        }
        if identity.kind in LEAF_KINDS:
            rows.append(row)
        elif depth >= max_depth or identity.name in ancestors:
            rows.append({**row, "kind": "RELATION_BOUNDARY"})
        else:
            rows.extend(
                _walk_fields(
                    client,
                    identity.name,
                    prefix=path,
                    depth=depth + 1,
                    max_depth=max_depth,
                    inherited_list=list_valued,
                    ancestors=ancestors | {identity.name},
                    cache=cache,
                )
            )
    return rows


def inventory_reachable_types(
    client: QueryClient,
    *,
    seed_types: list[str],
) -> list[dict[str, Any]]:
    """Catalog every field on every object type reachable from the entities.

    Field-path expansion has to stop at cycles.  A type graph does not: each type is
    queried exactly once, so this inventory covers the complete reachable schema
    without pretending an infinitely recursive selection can be fetched.
    """

    cache: dict[str, list[dict[str, Any]]] = {}
    pending = sorted(set(seed_types))
    seen: set[str] = set()
    catalog: list[dict[str, Any]] = []
    while pending:
        type_name = pending.pop(0)
        if type_name in seen:
            continue
        seen.add(type_name)
        fields = []
        for field in sorted(_type_fields(client, type_name, cache), key=lambda item: str(item.get("name") or "")):
            field_name = field.get("name")
            reference = field.get("type")
            if not isinstance(field_name, str) or not isinstance(reference, Mapping):
                continue
            identity = type_identity(reference)
            fields.append(
                {
                    "name": field_name,
                    "type": identity.name,
                    "kind": identity.kind,
                    "list_valued": identity.list_valued,
                    "deprecated": bool(field.get("isDeprecated", False)),
                    "deprecation_reason": field.get("deprecationReason"),
                }
            )
            if identity.kind in {"OBJECT", "INTERFACE"} and identity.name not in seen:
                pending.append(identity.name)
        catalog.append({"name": type_name, "fields": fields})
        pending.sort()
    return sorted(catalog, key=lambda item: str(item["name"]))


def inventory_entity(
    client: QueryClient,
    *,
    entity: str,
    selected_fields: str,
    max_depth: int = 3,
    query_field_catalog: Mapping[str, Mapping[str, Any]] | None = None,
    type_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Inventory all bounded leaf paths and compare them with the current query."""

    if max_depth < 1:
        raise ValueError("GraphQL inventory depth must be positive")
    available_query_fields = (
        dict(query_field_catalog)
        if query_field_catalog is not None
        else query_fields(client)
    )
    query_field = available_query_fields.get(entity)
    if query_field is None:
        raise ValueError(f"GraphQL query type lacks entity {entity}")
    identity = type_identity(query_field["type"])
    arguments = []
    for argument in query_field.get("args") or []:
        if isinstance(argument, Mapping) and isinstance(argument.get("name"), str) and isinstance(argument.get("type"), Mapping):
            argument_type = type_identity(argument["type"])
            arguments.append(
                {
                    "name": argument["name"],
                    "type": argument_type.name,
                    "kind": argument_type.kind,
                    "list_valued": argument_type.list_valued,
                }
            )
    fields = _walk_fields(
        client,
        identity.name,
        prefix="",
        depth=1,
        max_depth=max_depth,
        inherited_list=False,
        ancestors=frozenset({identity.name}),
        cache=type_cache if type_cache is not None else {},
    )
    selected = sorted(selected_paths(selected_fields))
    available = {str(field["path"]) for field in fields}
    return {
        "entity": entity,
        "entity_type": identity.name,
        "query_arguments": sorted(arguments, key=lambda item: str(item["name"])),
        "max_relation_depth": max_depth,
        "fields": fields,
        "selected_paths": selected,
        "selected_paths_absent_from_schema": sorted(set(selected) - available),
        "unselected_primitive_paths": sorted(
            field["path"]
            for field in fields
            if field["kind"] in LEAF_KINDS
            and not field["list_valued"]
            and not field["deprecated"]
            and field["path"] not in selected
        ),
        "unselected_list_primitive_paths": sorted(
            field["path"]
            for field in fields
            if field["kind"] in LEAF_KINDS
            and field["list_valued"]
            and not field["deprecated"]
            and field["path"] not in selected
        ),
    }
