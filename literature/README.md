# Literature Workspace

Keep the curated citation record compact, while separating source payloads from review authority. `papers/` holds local, gitignored source PDFs and inspected non-text companions; `text/` holds tracked searchable extracts plus the checksum index; `source-notes/` records source-family dispositions; `reviews/` holds explicitly historical synthesis digests. Current individual specialist cards and their index live in `docs/reviews/`, and the reconciled current ledger lives in `docs/literature-audit.md`.

Use `source-admission.json` as the source of truth for what may enter the curated corpus. Every source needs an explicit decision before acquisition, including peer-reviewed articles; a BibTeX entry type is metadata, not evidence of publication quality. Use `vehicle-currencies.bib` as the source of truth for citation metadata after admission, and `pdf-sources.json` only as the fetch manifest for admitted BibTeX keys: publisher PDF endpoints, public manuscript PDFs, authentication labels, and fallback routes for `scripts/fetch_literature.py`.

Use `use-contracts.json` as the executable bridge from completed evidence cards to live manuscript language. A claim-use contract records one adjudicated source boundary and the prohibited manuscript pattern that would violate it. A vocabulary contract applies only to a named term and a configured finance/economics publication class. Methodological silence never becomes a prohibition: a method is barred only by an explicit source prohibition recorded in a claim-use contract. Vocabulary silence may bar a configured term once the declared corpus-coverage floor is met.

Do not commit copyrighted PDFs or other files that cannot be redistributed. Keep private PDFs local and ignored; cite papers through DOI, URL, journal metadata, or BibTeX notes instead. Do not place review cards or digests inside `papers/`: that subtree is the source-payload boundary, not an agent-memory store.

Suggested filename pattern:

- `vehicle-currencies.bib` for the curated paper bibliography.
- `reading-notes.md` only if synthesis notes become useful; do not duplicate citation metadata outside BibTeX.

PDF fetching:

```bash
python3 scripts/fetch_literature.py
```

The tracked text index is also the portable checksum contract for the gitignored readable corpus. After adding or replacing PDFs, rebuild the index and verify it before another host enters a literature or review node:

```bash
./scripts/run scripts/build_literature_text_cache.py
./scripts/run scripts/build_literature_text_cache.py --check-corpus
```

The check requires an exact one-to-one match among PDFs, text extracts and index records and validates every PDF by SHA-256. The node-B findings gate applies the same rule to every required source set: a tracked extract cannot stand in for a missing main or companion PDF. An appendix may share the main PDF only when its source note declares `source_type: embedded-in-main`; a publisher-native HTML correction may close through `source_type: publisher-native-html`. An access-gap or unavailable note records discovery but cannot close a card marked `Companions: Complete`. Replication data and code archives remain outside this readable-corpus contract and retain their separate inspected-disposition checks.

The script validates every requested key against `source-admission.json` before it opens the network or writes a PDF. It then downloads PDFs to gitignored `literature/papers/` and writes a gitignored `literature/papers/download-manifest.json`. It tries committed sources in `pdf-sources.json` first, then generated DOI resolver fallbacks. For public servers that fail with Python's default HTTP stack, it falls back to `curl --http1.1`.

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

ScienceDirect / Elsevier fallback:

- First run the committed fetchers with `--prefer published`; if the stable ScienceDirect `pdfft` endpoint mints a signed `pdf.sciencedirectassets.com/...main.pdf?...` URL but plain `curl` or headless browser fetch gets 403 / HTML / accepted-manuscript fallback, use Java's authenticated Brave session as the access route.
- Open the stable endpoint in Brave with `open -a "Brave Browser" "https://www.sciencedirect.com/science/article/pii/<PII>/pdfft"` so ScienceDirect/OpenAthens mints the PDF route.
- Copy the real Brave profile to a temporary directory excluding caches, delete `Singleton*` lock files, and edit only the temp `Default/Preferences` so `plugins.always_open_pdf_externally=true` and `download.prompt_for_download=false`.
- Launch controlled Brave from `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` with `--user-data-dir=<tmp-profile> --profile-directory=Default --remote-debugging-port=<port> --no-first-run --no-default-browser-check about:blank`, attach Playwright over CDP, call `Browser.setDownloadBehavior` with a temp download path, navigate to the stable or page-inspected `pdfft?md5=...&pid=...` URL, then copy the downloaded `1-s2.0-<PII>-main.pdf` into gitignored `literature/papers/`.
- Verify the saved file with `file`, size, and page count, then delete the temp profile and download dir. Playwright/CDP may print Chrome-style labels because Brave is Chromium-based; the browser app is still Brave.

Known access routes:

- `Somogyi2026DollarDominanceFX`: use the UCL Primo `View Online` resolver and EBSCOhost Business Source Ultimate, then `Access now (PDF)`. The Primo/LibKey `Download PDF` button redirects to INFORMS and can hit Cloudflare/request-access instead of the licensed EBSCO PDF.

JSTOR note: try the stable PDF URL with `?acceptTC=1` before using the browser
fetcher, e.g. `https://www.jstor.org/stable/pdf/2234244.pdf?acceptTC=1`.
Some JSTOR PDFs that trigger browser automation access-checks still download
cleanly through the direct HTTP fetcher once the terms flag is present.
