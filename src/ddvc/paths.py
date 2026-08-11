"""Shared repository paths."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LITERATURE_DIR = REPO_ROOT / "literature"
# TWO ARTEFACTS, ONE PAPER.
#   memo/   the discovery draft. Every result, number and provenance comment, in the
#           register it was found in. Frozen for style; it is a record, not a deliverable.
#   paper/  the paper, written FROM the memo against the venue's measured shape bands.
# There is exactly one of each. A parallel "v2" copy of the paper was tried and removed,
# and the standing supersede-means-delete rule is why: two live copies of a deliverable
# already cost one full review cycle spent on the wrong file.
MEMO_DIR = REPO_ROOT / "memo"
PAPER_DIR = REPO_ROOT / "paper"


def prose_root() -> Path:
    """Whichever of the two currently holds the prose the gates should judge.

    The paper is the target once it exists. Until then the memo is the only prose in the
    repository, and measuring it is honest: the gates report how far the discovery draft
    sits from the venue, which is exactly the distance the rewrite has to travel.
    """
    return PAPER_DIR if (PAPER_DIR / "sections").is_dir() else MEMO_DIR


def sections_dir() -> Path:
    return prose_root() / "sections"
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"
V3_INVENTORY_RAW_ROOT = DATA_DIR / "raw" / "ethereum" / "uniswap_v3_inventory_events"
POOL_CAPITAL_PANEL = DATA_DIR / "processed" / "pool_capital_daily.parquet"
POOL_CANDIDATE_CAPITAL_PANEL = DATA_DIR / "processed" / "pool_candidate_capital_daily.parquet"
POOL_CAPITAL_REJECTIONS = DATA_DIR / "processed" / "pool_capital_rejections.parquet"
TOKEN_PRICE_DAILY_PANEL = DATA_DIR / "processed" / "token_price_daily.parquet"
EXTERNAL_WETH_USD_INTRADAY_PANEL = (
    DATA_DIR / "processed" / "external_weth_usd_intraday.parquet"
)
EXTERNAL_WETH_USD_RAW_ROOT = DATA_DIR / "raw" / "external" / "coinbase_exchange" / "eth_usd_spot_1m"
LP_CAPITAL_CONCENTRATION_PANEL = DATA_DIR / "exhibits" / "lp_capital_concentration.parquet"
LP_LIQUIDITY_FLOW_EVENTS = DATA_DIR / "processed" / "lp_liquidity_flow_events_v3.parquet"
LP_LIQUIDITY_FLOW_CANDIDATES = DATA_DIR / "processed" / "lp_liquidity_flow_candidates_v3.parquet"
LP_LIQUIDITY_FLOW_REJECTIONS = DATA_DIR / "processed" / "lp_liquidity_flow_rejections_v3.parquet"
LP_LIQUIDITY_FLOW_DAILY = DATA_DIR / "processed" / "lp_liquidity_flow_daily_v3.parquet"
MARKET_STATE_LOCK = DATA_DIR / "processed" / ".market_state.lock"
TOKEN_PRICE_LOCK = DATA_DIR / "processed" / ".token_price.lock"
ROUTE_COST_JOB_LOCK = DATA_DIR / "empirical" / ".route_cost_panel.lock"


def git_common_dir(repo_root: Path) -> Path | None:
    """Resolve the common git directory for a primary checkout or linked worktree."""
    marker = repo_root / ".git"
    if marker.is_dir():
        return marker.resolve()
    elif marker.is_file():
        try:
            prefix, value = marker.read_text(encoding="utf-8").strip().split(":", 1)
            if prefix != "gitdir":
                raise ValueError("invalid git worktree marker")
            git_dir = (repo_root / value.strip()).resolve()
            commondir = git_dir / "commondir"
            return (
                (git_dir / commondir.read_text(encoding="utf-8").strip()).resolve()
                if commondir.exists()
                else git_dir
            )
        except (OSError, ValueError):
            return None
    return None


def primary_checkout_root(repo_root: Path) -> Path:
    """Return the primary checkout shared by a linked worktree."""
    common = git_common_dir(repo_root)
    return common.parent if common and common.name == ".git" else repo_root


def literature_papers_dir(repo_root: Path) -> Path:
    """Return the one ignored PDF corpus shared by every linked worktree."""
    return primary_checkout_root(repo_root) / "literature" / "papers"


def _shared_git_runtime_dir(repo_root: Path) -> Path:
    """One untracked runtime directory shared by every linked worktree."""
    common = git_common_dir(repo_root) or DATA_DIR / ".locks"
    return common / "ddvc-runtime"


SHARED_RUNTIME_DIR = _shared_git_runtime_dir(REPO_ROOT)
PRIMARY_REPO_ROOT = primary_checkout_root(REPO_ROOT)
RAW_MARKET_DATA_LOCK = SHARED_RUNTIME_DIR / "raw-market-data.lock"
V3_INVENTORY_RANGE_LOCK_ROOT = SHARED_RUNTIME_DIR / "v3-inventory-range-locks"
EXTERNAL_WETH_USD_SOURCE_LOCK = SHARED_RUNTIME_DIR / "external-weth-usd.lock"


def repo_path(value: str | Path) -> Path:
    """Resolve a CLI path against the repository without changing absolute paths."""
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path

LITERATURE_BIB = LITERATURE_DIR / "vehicle-currencies.bib"
LITERATURE_PDF_SOURCES = LITERATURE_DIR / "pdf-sources.json"
LITERATURE_SOURCE_ADMISSION = LITERATURE_DIR / "source-admission.json"
LITERATURE_LOCAL_SOURCES = LITERATURE_DIR / "sources.local.json"
LITERATURE_AUTH_HEADERS = LITERATURE_DIR / "auth" / "headers.local.json"
LITERATURE_PAPERS_DIR = literature_papers_dir(REPO_ROOT)
LITERATURE_DOWNLOAD_MANIFEST = LITERATURE_PAPERS_DIR / "download-manifest.json"
