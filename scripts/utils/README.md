# Utilities

This folder contains small repository operations that do not own scientific
data. `report_research_runtime.py` reports current process and resource state.
`embed_deck_video.py` replaces the deck's LaTeX file-link marker with a
self-contained Acrobat RichMedia annotation. Run it after every deck rebuild;
`--verify-only` checks the embedded bytes and rejects external launch actions.
