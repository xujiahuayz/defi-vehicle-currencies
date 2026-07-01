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

The script downloads PDFs to gitignored `literature/papers/` and writes a gitignored `literature/papers/download-manifest.json`. It tries each BibTeX DOI as the published source, then committed fallbacks in `pdf-sources.json`.

For authenticated or paywalled URLs that Java can access legitimately:

- Put additional local-only source URLs in `literature/sources.local.json` using `sources.example.json` as the template.
- Put local-only cookie/header material in `literature/auth/headers.local.json` using `auth.example.json` as the template.
- Re-run `python3 scripts/fetch_literature.py --strict` when auth is in place.
