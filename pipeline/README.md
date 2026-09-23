# Data pipeline

Sources (checked 2026-09-23):

| Program | Source | How |
|---|---|---|
| ASTC | abridged participant PDF (astc.org) | live, monthly |
| ACM | findachildrensmuseum.org JSON API | live, monthly |
| NARM | quarterly member-list PDF (the search pages are robots-disallowed) | live, monthly |
| ROAM | member-list PDF linked from the ROAM Google Site (Drive) | live, monthly; falls back to a stale mirror if Drive fails |
| AHS | garden-network map data embedded in ahsgardening.org | live, monthly |
| AZA | annual reciprocity PDF | **manual drop** — aza.org opts out of automated access |
| Time Travelers | "List of Member Institutions" page, saved from a browser (.htm) | **manual drop** — robots.txt disallows all agents |
| ANCA | nature-center member table on natctr.org/membership/reciprocal-program | live, monthly |

Per-museum rules the sources mark are kept on each program entry: `exclusion`
(ROAM "+" 25 mi, NARM 15/50 mi, AHS "Local Visitor Exception" 90 mi from home,
ANCA "excludes organizations within 50 miles")
and `tier` (AZA "100% OR 50%", free between same-tier zoos).

Geocoding is offline first: ZIP centroid, else the Census place + town table
(`place_centroids.json`, from `geodata.py`), else `GEO_OVERRIDES` in build.py,
else a structured Nominatim lookup cached in `geocode_cache.json` (committed).
Listings of one museum under different names are merged by `same_museum()`
plus the explicit `SAME_MUSEUM` aliases in build.py.

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

AZA and Time Travelers opt out of automated access (robots.txt / bot
challenge), so they are fed **only** this way. Drop a PDF as-is: the next
build writes a same-named `.txt` extract beside it. Commit the `.txt` only —
`manual_drops/**/*.pdf` is gitignored so we don't republish the association's
document. Replace the AZA drop each May (its list runs May–April).

## ZIP and place centroids (`geodata.py`)
`data/zip_centroids.json` maps every US ZIP (Census ZCTA, ~34k) to a centroid;
the app uses it to resolve the home ZIP (residence anchor for distance rules)
and the "find museums near" ZIP offline. ZCTAs change rarely, so this is run by
hand rather than monthly: `python pipeline/geodata.py`, which also writes
`data/places.json` (every US place/town with a display name, for the app's
city autocomplete and city resolver). After rebuilding,
bump `CACHE` in `sw.js` (the file is served cache-first).
