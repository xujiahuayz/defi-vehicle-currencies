"""Canonical JFE exemplar ownership and local artifact resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ddvc.paths import LITERATURE_PDF_SOURCES, PRIMARY_REPO_ROOT, REPO_ROOT


JFE_VENUE_SOURCE_KEYS = {
    "venue:bolton-kacperczyk-carbon": "BoltonKacperczyk2021CarbonRisk",
    "venue:carletti-banks-patient-lenders": "CarlettiDeMarcoIoannidouSette2021PatientLenders",
    "venue:chang-ripples-into-waves": "ChangDuLouPolk2022Ripples",
    "venue:cong-li-wang-token-platform": "CongLiWang2022TokenPlatform",
    "venue:diamond-hu-rajan-liquidity-pledgeability": "DiamondHuRajan2022LiquidityPledgeability",
    "venue:eren-malamud-dominant-currency-debt": "ErenMalamud2022DominantDebt",
    "venue:graham-corporate-culture": "GrahamGrennanHarveyRajgopal2022CorporateCulture",
    "venue:hajda-nikolov-product-market": "HajdaNikolov2022ProductMarket",
    "venue:hinzen-bitcoin-adoption": "HinzenJohnSaleh2022LimitedAdoption",
    "venue:huang-constrained-liquidity-fx": "HuangRanaldoSchrimpfSomogyi2025Constrained",
    "venue:li-ye-zheng-refusing-best-price": "LiYeZheng2023Refusing",
    "venue:makarov-schoar-crypto-arbitrage": "MakarovSchoar2020Arbitrage",
    "venue:mayer-financing-breakthroughs": "Mayer2022FinancingBreakthroughs",
    "venue:pastor-sustainable-investing": "PastorStambaughTaylor2021SustainableInvesting",
}
JFE_VENUE_CARDS = frozenset(JFE_VENUE_SOURCE_KEYS)


@dataclass(frozen=True)
class VenueCorpus:
    """Resolved version-of-record PDFs plus any source keys missing locally."""

    pdfs: tuple[Path, ...]
    missing: tuple[str, ...]


def resolve_venue_corpus(
    *,
    repo_root: Path = REPO_ROOT,
    primary_root: Path = PRIMARY_REPO_ROOT,
    source_registry: Path = LITERATURE_PDF_SOURCES,
) -> VenueCorpus:
    """Resolve each exemplar from its canonical source-set article, with worktree fallback."""
    try:
        source_sets = json.loads(source_registry.read_text()).get("source_sets", {})
    except (json.JSONDecodeError, OSError):
        source_sets = {}

    pdfs: list[Path] = []
    missing: list[str] = []
    roots = tuple(dict.fromkeys((repo_root.resolve(), primary_root.resolve())))
    for source_key in JFE_VENUE_SOURCE_KEYS.values():
        source_set = source_sets.get(source_key, {})
        article = source_set.get("checks", {}).get("article") if isinstance(source_set, dict) else None
        if not isinstance(article, str) or not article.startswith("literature/text/"):
            missing.append(source_key)
            continue
        filename = f"{Path(article).stem}.pdf"
        resolved = next(
            (
                root / "literature" / "papers" / filename
                for root in roots
                if (root / "literature" / "papers" / filename).is_file()
            ),
            None,
        )
        if resolved is None:
            missing.append(source_key)
        else:
            pdfs.append(resolved)
    return VenueCorpus(tuple(pdfs), tuple(missing))
