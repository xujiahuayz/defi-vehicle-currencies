from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TX = "0xbda1d07f17c503b5a9c8117c5d1383472006af8a9e22aa4e5e30804b9bf67ad9"


def test_paper_and_deck_define_the_same_etherscan_link_macro() -> None:
    definition = r"\newcommand{\ethtx}[2]{\href{https://etherscan.io/tx/#1}{\texttt{#2}}}"
    assert definition in (ROOT / "paper/main.tex").read_text(encoding="utf-8")
    assert definition in (ROOT / "deck/main.tex").read_text(encoding="utf-8")


def test_visible_example_transaction_uses_full_hash_as_link_target() -> None:
    paper = (ROOT / "paper/sections/02-setting.tex").read_text(encoding="utf-8")
    deck = (ROOT / "deck/sections/01-identification.tex").read_text(encoding="utf-8")
    target = rf"\ethtx{{{TX}}}{{"
    assert paper.count(target) == 1
    assert deck.count(target) == 2
    assert r"\texttt{0xbda1d07f\ldots" not in paper
    assert r"\texttt{0xbda1d07f\ldots" not in deck
