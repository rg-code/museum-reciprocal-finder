# Data pipeline

Build order: **ASTC + ACM first**, then NARM, ROAM, AZA, AHS, Time Travelers.

Flow: scrape/parse each source -> normalize to the common schema -> geocode
(cached) -> dedupe & merge -> validate (guardrail) -> emit `data/*.json`.

## Adapters (`adapters/`)
One per source. Each emits records in the common schema tagged with its program.
Prefer a hidden JSON/XHR endpoint > HTML parse > headless browser. PDFs via
pdfplumber. See `docs/ARCHITECTURE.md` §7.

## Manual drops (`manual_drops/`)
Drop an association-supplied PDF/CSV of participating institutions here to have
the pipeline parse it instead of scraping (ToS-safe). Record it in
`manual_drops/index.json`; a manual drop overrides the scraper for that
program + month.
