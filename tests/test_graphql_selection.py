from __future__ import annotations

import pytest

from ddvc.fetch.graphql_selection import render_selection, selected_paths


def test_selection_round_trip_is_deterministic() -> None:
    paths = {"id", "transaction.id", "transaction.blockNumber", "pool.token0.id"}
    rendered = render_selection(paths)
    assert rendered == "id pool { token0 { id } } transaction { blockNumber id }"
    assert selected_paths(rendered) == paths


def test_selection_parser_uses_alias_as_response_key() -> None:
    assert selected_paths("feeTier: fee id") == {"feeTier", "id"}


@pytest.mark.parametrize("path", ["", ".id", "id.", "pool..id"])
def test_selection_renderer_rejects_malformed_paths(path: str) -> None:
    with pytest.raises(ValueError):
        render_selection({path})
