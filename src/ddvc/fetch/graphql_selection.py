"""Canonical parsing and rendering for compact GraphQL field selections."""

from __future__ import annotations

import re


def selected_paths(selection: str) -> set[str]:
    """Return response-key paths from a compact GraphQL selection."""

    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[{}:]", selection)

    def parse(index: int, prefix: str) -> tuple[set[str], int]:
        paths: set[str] = set()
        while index < len(tokens) and tokens[index] != "}":
            response_key = tokens[index]
            index += 1
            if index < len(tokens) and tokens[index] == ":":
                index += 2
            path = f"{prefix}.{response_key}" if prefix else response_key
            if index < len(tokens) and tokens[index] == "{":
                nested, index = parse(index + 1, path)
                paths.update(nested)
            else:
                paths.add(path)
        return paths, index + int(index < len(tokens) and tokens[index] == "}")

    paths, consumed = parse(0, "")
    if consumed != len(tokens):
        raise ValueError("GraphQL selection parser did not consume the field contract")
    return paths


def render_selection(paths: set[str] | list[str] | tuple[str, ...]) -> str:
    """Render dotted response paths into a deterministic compact selection."""

    tree: dict[str, dict] = {}
    for path in sorted(set(paths)):
        if not path or path.startswith(".") or path.endswith(".") or ".." in path:
            raise ValueError(f"invalid GraphQL response path: {path!r}")
        current = tree
        parts = path.split(".")
        for part in parts:
            current = current.setdefault(part, {})

    def render(node: dict[str, dict]) -> str:
        fields = []
        for name, children in sorted(node.items()):
            fields.append(f"{name} {{ {render(children)} }}" if children else name)
        return " ".join(fields)

    return render(tree)
