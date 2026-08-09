#!/usr/bin/env python3
"""Build the published positive-support Uniswap--Binance token registry."""

from __future__ import annotations

from ddvc.analysis.cex_reference import build_cex_reference_support
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.tables import write_panel


SOURCE = (
    REPO_ROOT
    / "literature"
    / "papers"
    / "2024-LeharParlour2024UniswapReplicationCode-supplement-replication-code.zip"
)
OUTPUT = DATA_DIR / "processed" / "cex_reference_support.parquet"
CODE_SOURCES = [
    "scripts/process/build_cex_reference_support.py",
    "src/ddvc/analysis/cex_reference.py",
]


if not SOURCE.is_file():
    raise SystemExit(f"missing validated published replication package: {SOURCE.relative_to(REPO_ROOT)}")

support = build_cex_reference_support(SOURCE)
write_panel(
    support,
    OUTPUT,
    code_sources=CODE_SOURCES,
    inputs=[SOURCE],
    notes=(
        "positive observed Uniswap-Binance support only; the source minute data are a "
        "1-in-10,000 audit sample through 2022; absence never means unlisted"
    ),
)
print(
    f"wrote {OUTPUT.relative_to(REPO_ROOT)}: {len(support):,} exact-address tokens; "
    f"sample observations={int(support['binance_sample_rows'].sum()):,}; "
    f"range={support['binance_sample_first_at'].min()}..{support['binance_sample_last_at'].max()}"
)
