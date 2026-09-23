# Museum Reciprocal Finder

A static Progressive Web App (PWA), hosted on GitHub Pages, that tells you which
museums you can enter **free** or at a **discount** based on the reciprocal
networks your membership(s) belong to — accounting for the distance rules that
block nearby institutions.

> **Status:** architecture / design phase. No application code yet — this repo
> currently holds the design docs, seed data, and repo scaffold.

## What it does
- You enter your membership (by home museum, by association, or "none yet"),
  plus a location (ZIP, city, or address).
- It classifies nearby museums as **Free / ~50% off / Verify / Not covered**,
  color-coded by association, and recommends the best association when a museum
  is in several of your networks.
- If you have no membership, it recommends the **cheapest gateway membership**
  that unlocks the most reciprocal access ("membership arbitrage").

## Networks covered
ASTC · NARM · ROAM · AZA · AHS · Time Travelers · ACM · ANCA  (US only, v1)

## Repo layout
```
docs/        Architecture, eligibility flow diagram, project memory
data/        Seed + generated data (museums.json, programs.json, memberships.json, ...)
app/         PWA frontend (Vite + React) — engine/ holds the pure eligibility logic
pipeline/    Python scrapers + build; manual_drops/ for association-supplied PDFs
.github/     Monthly data-refresh + Pages deploy workflows
```

## Docs
- [Architecture & implementation plan](docs/ARCHITECTURE.md)
- [Eligibility decision flow](docs/eligibility-flow.mermaid)
- [Project memory](docs/PROJECT-MEMORY.md)

## Roadmap (short)
0. Data spike — prove each source is parseable (ASTC + ACM first)
1. MVP finder — engine + three entry paths + results
2. Automated monthly pipeline
3. PWA polish (map, offline)
4. Arbitrage advisor, admission pricing

## Disclaimer
Reciprocal policies are set by each institution and change often. This tool is
guidance only — always confirm with the museum before you visit.
