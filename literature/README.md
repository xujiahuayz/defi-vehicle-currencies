# Literature Workspace

This folder is intentionally flat. Keep the durable literature record in BibTeX so the paper can compile from a small curated bibliography rather than a large omnibus file.

Do not commit copyrighted PDFs or other files that cannot be redistributed. Keep private PDFs local and ignored; cite papers through DOI, URL, journal metadata, or BibTeX notes instead.

Suggested filename pattern:

- `vehicle-currencies.bib` for the curated paper bibliography.
- `reading-notes.md` only if synthesis notes become useful; do not duplicate citation metadata outside BibTeX.

PDF fetching:

```bash
python3 scripts/fetch_literature.py
```

The script downloads PDFs to gitignored `literature/papers/` and writes a gitignored `literature/papers/download-manifest.json`. It tries committed sources in `pdf-sources.json` first, then generated DOI resolver fallbacks. For public servers that fail with Python's default HTTP stack, it falls back to `curl --http1.1`.

Discover publisher-registered PDF endpoints from DOI metadata:

```bash
python3 scripts/discover_pdf_sources.py --write
```

Authenticated browser fetching:

```bash
UCL_USER=... UCL_PW=... /path/to/python scripts/fetch_literature_browser.py
```

The browser fetcher uses a gitignored persistent profile under `literature/auth/browser-profile`, supports OpenAthens/UCL login, extracts raw PDF responses/downloads, and mines article pages for PDF links advertised in metadata or buttons. It is reproducible once credentials/session state are available, but some publishers still block headless/browser automation with access checks or subscription walls.

For authenticated or paywalled URLs that Java can access legitimately:

- Put additional local-only source URLs in `literature/sources.local.json` using `sources.example.json` as the template.
- Put local-only cookie/header material in `literature/auth/headers.local.json` using `auth.example.json` as the template.
- Re-run `python3 scripts/fetch_literature.py --strict` when auth is in place.

Known current access limits:

- `Krugman1980VehicleCurrencies`: the NBER working paper is available locally; JSTOR published PDF is blocked by the same access check.
- `Somogyi2026DollarDominanceFX`: INFORMS shows request-access under current auth; the UniCredit working-paper PDF is available locally.

JSTOR note: try the stable PDF URL with `?acceptTC=1` before using the browser
fetcher, e.g. `https://www.jstor.org/stable/pdf/2234244.pdf?acceptTC=1`.
Some JSTOR PDFs that trigger browser automation access-checks still download
cleanly through the direct HTTP fetcher once the terms flag is present.
