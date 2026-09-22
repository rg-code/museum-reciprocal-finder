# Museum App — Project Memory

*Persistent context for the "Museum Reciprocal Finder" project. Hand this to any future session (or add it to the project's knowledge) so it starts with full context.*
*Last updated: 2026-09-22*

> Tip: this file lives in the workspace/outputs folder. To have future sessions auto-load it, add it to this Claude Project's knowledge (the read-only knowledge folder can't be written from a session).

---

## 1. What we're building

A **static PWA hosted on GitHub Pages** that tells the user which museums they can enter **free** or at a **discount** based on the reciprocal networks their membership(s) belong to. No server, no DB, no cost. Monthly data refresh via GitHub Actions. **Currently in architecture/design phase — no code yet.**

Full design: `museum-reciprocal-app-architecture.md`. Eligibility flow: `eligibility-flow.mermaid`. Gateway seed data: `memberships.seed.json`.

---

## 2. Locked decisions

- **Platform:** static PWA on GitHub Pages (all logic client-side).
- **Data:** automated monthly scraper via GitHub Action **+ manual PDF/CSV drop folder** (`/pipeline/manual_drops/`) for association-supplied lists / ToS-safe sourcing.
- **Discount handling (v1):** classify only — **Free / ~50% / Verify / Not covered**. No dollar math in v1 (schema reserves a price field for v2).
- **ZIP/location required:** drives distance-exclusion rules. Input accepts **ZIP, city, or address** (resolver → coordinates).
- **Geographic scope:** **US only** for v1.
- **Adapter build order:** **ASTC + ACM first**, then the rest.
- **Feature priority:** build the **free/discount finder first**; the **gateway/arbitrage advisor** comes next (both wanted).
- **Scope:** personal use — don't over-engineer edge cases.

---

## 3. The 7 reciprocal programs (benefit + distance rule)

| Program | Benefit | Distance / exclusion rule |
|---|---|---|
| **ASTC** (science) | Free | 90 mi, "as the crow flies". **OR logic**: blocked if within 90 mi of your home institution **OR** your residence. Both must be >90 mi to get in free. |
| **NARM** (~1,500, mixed) | Free (+ shop/lecture discounts) | Per-institution; commonly ~15 mi home-institution exclusion. Varies. |
| **ROAM** (~500) | Free | 25 mi (40 km) between member institutions. |
| **AZA** (zoos/aquariums) | **50%–free, set per institution** | Per-institution proximity exclusions. |
| **AHS** (gardens, ~350) | Free | Optional 90 mi (garden may apply, based on card address). |
| **Time Travelers** (history, ~400) | Per institution: free or reduced | No central distance rule. |
| **ACM** (children's, ~200) | **50% off, up to 6 people** | **No 90-mile rule.** |

**Key modeling insight:** benefit tier and distance rule are frequently **per-institution, not uniform per program** → store benefit + exclusion **per museum, per program**, with program-level defaults as fallback.

**Validation reality (from prior research):** none of these networks runs a central member database. Front-desk check = current card bearing the network logo + matching photo ID; the only cross-check is a venue optionally phoning your home institution. ASTC states "no universal database" verbatim; the others establish it by mechanism. (Out of scope for the app, but useful context.)

---

## 4. Cheapest / best gateway memberships (seed data)

For the "no membership yet" recommender. Full data + notes in `memberships.seed.json`. **Prices approximate — reconfirm on museum sites.**

- **Cheapest ASTC-only:** Western Science Center (Hemet, CA) ~$45 individual.
- **3 networks cheaply:** Dennos Museum Center (Traverse City, MI) ~$100 family = ASTC + NARM + ROAM. (Prior research also cited a "Carnegie (IN)" at similar price — still needs pinning down.)
- **Most networks + digital card (winner):** **Kern County Museum** (Bakersfield, CA) ~$125 = ASTC + NARM + ACM + Time Travelers (maybe ROAM), Join It wallet card (card face shows only Kern seal, no reciprocal logos).
- **Only AZA gateway with a digital card:** Boonshoft (Dayton, OH) ~$135 family = ASTC + AZA + ACM.
- **Time Travelers + digital card:** Cincinnati Museum Center ~$140 family = ASTC + Time Travelers + ACM; also Peoria Riverfront Museum = ASTC + NARM + Time Travelers.
- **Adds AHS (hardest network):** Newfields (Indianapolis) = NARM + ROAM + AHS, digital card.
- **Highest raw coverage (but physical-card only):** New Britain Museum of American Art (CT) = ASTC + NARM + ROAM + AHS + ACM; New Jersey State Museum (~$250 Sponsor) = ASTC + NARM + ROAM + Time Travelers.
- **2026 ASTC price floor:** ~$40 individual / ~$100 family.
- **No single membership** covers Time Travelers + ROAM + AHS together (they rarely co-occur); minimum 2 memberships to get all.

Networks **out of scope** for the app but seen in research: **MARP** (~30 art museums), **ANCA** (nature centers).

Authoritative source for the pipeline: **ASTC Travel Passport participant list PDF** (refreshed each May), e.g. `astc.org/wp-content/uploads/2026/04/Standard-List-11pt-Font.pdf`.

---

## 5. User's current memberships (Rohit)

Confirmed from official pages in the prior chat. Could prefill the app's default profile.

- **Museum of Science, Boston** (MA) — ASTC + AZA (all levels). Digital card. *Only AZA source.*
- **Indiana State Museum & Historic Sites** (IN) — ASTC (all levels) + NARM (**only at Family Plus $179+ / Donor $250+**). Digital card. *Only NARM source.* No Time Travelers.
- **Please Touch Museum** (Philadelphia, PA) — ACM only. Digital card.
- **New Britain Museum of American Art** (CT) — ASTC, NARM, ROAM, AHS, ACM. **Physical card only** (user lost physical card, has a scan).

Together these cover **ASTC, AZA, NARM, ACM** (and via New Britain: ROAM, AHS). Missing from the 7: **Time Travelers**. (Also missing out-of-scope MARP.)

---

## 6. Open items

1. Verify approximate prices in `memberships.seed.json` (several marked `approx`/`verify`).
2. Pin down the "Carnegie (IN)" gateway from prior research.
3. Decide whether to prefill the app with Rohit's current memberships as the default profile.
4. When coding starts: build ASTC + ACM adapters first; stand up the eligibility engine with unit tests before the UI.

---

## 7. Files in this project

- `museum-reciprocal-app-architecture.md` — full architecture & implementation plan (v0.2).
- `eligibility-flow.mermaid` — per-museum Free/50%/Verify/Not-covered decision flow + overlap recommendation.
- `memberships.seed.json` — seed catalog of 9 gateway memberships.
- `project-memory.md` — this file.
