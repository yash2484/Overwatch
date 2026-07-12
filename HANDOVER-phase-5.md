# Handover — Phase 5 (OSINT Fusion), paused after Task 8

> **Written:** 2026-07-12, end of session.
> **Branch:** `phase-5-osint-fusion` — clean tree, all work committed, **268 tests passing**.
> **Progress:** **Tasks 1–8 of 12 done.** Resume at **Task 9**.
> **Read first:** `plans/2026-07-12-phase-5-osint-fusion.md` (the plan you are executing) and
> `design-specs/2026-07-12-phase-5-osint-fusion-design.md` §2 (the spike evidence — it explains *why* the design is
> shaped this way, and will stop you "fixing" things that are deliberate).

---

## 1. Start here (literally)

```bash
# Docker Desktop does NOT auto-start on this machine. Start it, then:
docker compose up -d
docker compose exec -T api pytest -q          # expect: 268 passed
docker compose exec -T api alembic current    # expect: 0004 (head)
docker compose exec -T api ruff check .       # expect: All checks passed!
git branch --show-current                     # expect: phase-5-osint-fusion
```

If that all matches, the handover is intact and you can go straight to Task 9.

**Workers do not hot-reload.** After touching `overwatch/workers/*`: `docker compose restart worker beat`.
After touching `pyproject.toml` or the Dockerfile: `docker compose up -d --build api worker beat`.

---

## 2. What is DONE (Tasks 1–8)

| # | Task | Commit | What landed |
|---|---|---|---|
| 1 | Migration 0004 + ORM | `2f02de1` | `news_articles` (**no geometry column** — deliberate), `aois.place_terms`/`region_terms`, `evidence_links.article_id` + CHECK |
| 2 | Presets + AOI terms + settings | `40fedef` | `FUSION_PRESETS` with spike-verified GDELT theme IDs; `httpx` promoted to a runtime dep |
| 3 | Text normalization | `8b72e35` | `normalize`, `match_terms` (whole-word), `match_stems` (prefix) |
| 4 | **Three-gate scorer** + window fix | `31693bb` | `score_article` — the TDD centrepiece. **Plus the capped-interval window correction (see §3).** |
| 5 | Syndication dedup | `21fb384` | `dedupe` — one wire story cites once, not twice |
| 6 | GDELT provider | `40d1a68` | `GdeltDocProvider` (plaintext 429/200 handling, 6 s throttle), `FakeNewsProvider`, fixtures |
| 7 | Article persistence | `3ec9796` | `replace_articles` (replace-set, idempotent, flips validated briefs → `stale`), `articles_for_pair` |
| 8 | **Validator Gate 4** | `b6e1de1` | The observed/reported wall. Journalism may never wear the clothes of sensing. |

New module: `backend/src/overwatch/fusion/` — `models.py`, `presets.py`, `normalize.py`, `scorer.py`, `provider.py`.
New repo: `backend/src/overwatch/db/news.py`.
New tests: `test_fusion_{presets,normalize,scorer,dedup,provider}.py`, `test_news_db.py`, `test_brief_validator_gate4.py`.

---

## 3. ⚠️ The one thing you must not undo: the window was corrected mid-execution

The approved design (decision 3) anchored the temporal gate on the **after-scene** — a 44-day band. It passed design
review and then **failed against reality**, which is exactly why we execute against real data.

Novo Progresso's **actual** scene pair in Postgres is `2023-07-30 → 2024-07-24`. The after-anchored band is therefore
`2024-06-24 … 2024-08-07`, and **a live GDELT query over that exact window returns ZERO articles.** All four demo
articles (Aug–Sep 2023) sit ~11 months earlier. The forest AOI — our best fusion story — would have shipped with **no
news section at all.**

Deforestation coverage lands **when the clearing happens**, spread across the observation interval. The after-scene is
when *we looked*, not when *it happened*.

**The fix, now in `FusionWindow.around(before, after, preset)`:**

```
start = max(before_scene, after_scene − max_lookback_days) − lead_days
end   = after_scene + lag_days
```

Verified against **all three real pairs** (these numbers are asserted in `test_fusion_presets.py`):

| AOI | Real pair (gap) | Window | Why it's right |
|---|---|---|---|
| Novo Progresso | 2023-07-30 → 2024-07-24 (360 d) | 2023-06-30 … 2024-08-07 | admits the Aug-2023 stories |
| Vizhinjam | 2021-02-12 → 2025-02-11 (**1,460 d**) | 2023-12-09 … 2025-02-25 | **~14 months, not 4 years** — the cap is the anti-vacuity guard |
| Porto Alegre | 2024-04-18 → 2024-05-21 (33 d) | 2024-03-19 … 2024-06-04 | tight, because the event was |

**Rule for the rest of this phase: derive test windows from real scene pairs via `FusionWindow.around()`. Never
hand-invent dates.** Hand-invented dates are precisely what let this bug survive design review.

---

## 4. NEXT UP — Task 9 (start here)

**Task 9: prompt + persistence carry articles.** Plan file, "Task 9". Three edits:

1. **`backend/src/overwatch/briefs/prompt.py`** — render a `SOURCES` block when `request.articles` is non-empty
   (it's already on `BriefRequest`, done in Task 8). Cap at `settings.fusion_max_prompt_articles` (=10) and **log the
   truncation** — carry Phase 4's prompt-size discipline. The block must state the rules the model has to obey, because
   the validator will enforce them: reported-speech framing, no quantities, `mixed` needs both sides.

2. **`backend/src/overwatch/db/briefs.py`** — `persist_validated`'s `claims` param becomes a **4-tuple**:
   `list[tuple[str, str, list[int], list[int]]]` = `(text, claim_type, detection_ids, article_ids)`. Add the
   article `EvidenceLink` loop alongside the existing detection one:
   ```python
   for article_id in article_ids:
       session.add(EvidenceLink(claim_id=claim.id, evidence_type="article", article_id=article_id))
   ```

3. **`backend/src/overwatch/workers/tasks.py`** — `_build_brief_request` loads `articles_for_pair(...)` and passes
   `articles=[ArticleRow(...)]`; `generate_brief`'s `persist_validated` call passes the 4th tuple element
   (`c.article_evidence`).

> ⚠️ **`persist_validated` is called from two places.** Changing its signature will break `test_briefs_db.py` and
> `test_brief_task.py` — update their call sites to the 4-tuple form. This is expected, not a regression.

**Then:** Task 10 (`fuse` Celery task + chain wiring + kill-switch), Task 11 (`POST /aois/{slug}/fusion`),
Task 12 (verification gate). All three are fully specified in the plan with real code.

---

## 5. Landmines — read these before you debug something

- **GDELT rate-limits hard.** HTTP **429 with a PLAINTEXT body** (never `json.loads` a GDELT response blind), and a
  **200 can also carry a plaintext error**. Both are handled in `provider.py` and both have fixtures. During this
  session GDELT needed **~75 s** to clear after a burst. The live gate (Task 12) will hit this — space the calls out.
- **CI never touches the network.** All provider tests replay recorded fixtures via `FakeNewsProvider`. Keep it that way.
- **`sourcecountry` is a trap.** It's the *publisher's registration country*, not the story's location — Mongabay's
  Pará story returns `"Indonesia"`. It's stored in `meta` as provenance only. **Never use it as geography.**
- **Do not rebuild the geofence.** GDELT exposes no article geotag; GEO 2.0 404s; and BigQuery/GGG is the *same
  geocoder* — GDELT documents it as centroid-based. We measured it rejecting **100% of our true positives**. Full
  evidence in design §2.4/§2.4b and `CONTEXT.md`. Gate 1 is a **toponym** gate and must never be called "spatial".
- **Titles omit the place name.** Zero of six Porto Alegre and zero of four Novo Progresso articles name their AOI in
  the title. That's why retrieval uses the **strict** term (full text, GDELT-side) and the scorer corroborates with a
  **generous** list including regional names. Don't "tidy" `region_terms` down to just the city — you'll score 0/4.
- **A transient Docker build failure happened once** (`beat` failed while `api` succeeded, same Dockerfile). Rebuilding
  worked. If a build fails, retry before investigating — but **verify the container actually restarted on the new
  image**, because tests will otherwise pass against the *old* image and give you a false green. That happened this
  session and was caught.

---

## 6. State of the wider project

- **Phases 0–4 merged to main and green.** Phase 4's **live gate is still pending** — it needs
  `OVERWATCH_ANTHROPIC_API_KEY` in `.env` (user supplies directly; never committed, never in chat). Phase 5 does **not**
  need it — all 268 tests use `FakeBriefGenerator`/fixtures — but **Task 12's live gate will**.
- **This branch also carries the Phase 5 + 6 planning docs** (merged in from `phase-5-6-planning`, commit `81722e4`), so
  it is self-contained: design + plan + implementation in one PR.
- **Phase 6 is fully planned and untouched**: `plans/2026-07-12-phase-6-frontend-arena.md`. Do Phase 5 first — Phase 6's
  brief panel renders Phase 5's article citations.
- **Deferred to v0.2** (recorded, not forgotten): two-tier proximate/contextual windows; non-English articles; GGG's
  `ContextualText` (600-char snippets) as a better substrate for the toponym/thematic gates — with the exact free-tier
  BigQuery query that would justify it, in design §2.4b.
- **Folded into Task 8, now done:** the stashed Phase-4 "Gate-3 unrecognized-unit" hardening was superseded — the
  validator was reworked wholesale for Gate 4.

---

## 7. Definition of done for this phase (design §8)

1. Real correlated articles cited for ≥1 AOI, every citation resolving to a `news_articles` row (SQL join proof).
2. A deliberately irrelevant article demonstrably rejected — **the money shot is already passing as a unit test:**
   *"Amazon Prime Day deals announced"* **fires the toponym gate on "Amazon"** and the AND rejects it anyway.
3. `FUSION_ENABLED` tested both ways.
4. Gate 4 rejects an article-only claim wearing observational framing. ✅ *(done — Task 8)*
5. Re-run → zero duplicate rows; a validated brief on the re-fused pair flips to `stale`. ✅ *(done — Task 7)*
