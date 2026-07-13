# Handover — Phase 5, the last two verification items

> **Written:** 2026-07-13, end of session.
> **Branch:** `phase-5-osint-fusion` — clean tree, all work committed, **289 tests passing**.
> **State:** **All 12 tasks are BUILT.** The verification gate is *partially* done. Two items remain, and **neither is
> blocked on code** — one needs an API key, one needs GDELT to stop rate-limiting our IP.
> **Supersedes:** `HANDOVER-phase-5.md` (that one got you to Task 9; Tasks 9–12 are now done).

---

## 1. Start here

```bash
docker desktop start                          # does NOT auto-start on this machine
docker info                                   # poll until it answers
cd /c/dev/Overwatch && docker compose up -d

docker compose exec -T api pytest -q          # expect: 289 passed
docker compose exec -T api ruff check .       # expect: All checks passed!
docker compose exec -T api alembic current    # expect: 0004 (head)
git branch --show-current                     # expect: phase-5-osint-fusion
```

**Shut down in this order when you finish** (the user asked for this explicitly — idle containers and the WSL2 VM cost
real RAM on a 16 GB laptop):

```bash
docker compose down     # NEVER -v — that destroys the DB, see §5
docker desktop stop     # must go BEFORE wsl --shutdown, or it respawns the distro
wsl --shutdown          # kills vmmemWSL
wsl --list --running    # verify: "There are no running distributions."
```

**Workers do not hot-reload.** After touching `overwatch/workers/*` or `overwatch/fusion/*`:
`docker compose restart worker beat`.

---

## 2. What is left — exactly two things

### Item A — the SQL join proof + the live stale flip (needs the Anthropic key)

This is DoD #1 and the live half of #5: *real articles cited by a real, model-authored, validated brief, with every
citation resolving to a `news_articles` row.*

1. The user creates `c:\dev\Overwatch\.env` (gitignored) containing:
   ```
   OVERWATCH_ANTHROPIC_API_KEY=sk-ant-...
   ```
2. `docker compose up -d --force-recreate api worker beat` (compose interpolates it in — **verified working**, see §3).
3. Confirm the container actually sees it — do not skip this, it is the whole reason Phase 4's gate never ran:
   ```bash
   docker compose exec -T api python -c "from overwatch.config import settings; print(bool(settings.anthropic_api_key))"
   # expect: True
   ```
4. Fuse an AOI (see Item B — you need articles in the DB first), then `POST /aois/{slug}/briefs`, poll to `validated`,
   and run the join:
   ```sql
   SELECT bc.seq, bc.claim_type, na.domain, na.title
   FROM briefs b
   JOIN brief_claims bc  ON bc.brief_id = b.id
   JOIN evidence_links el ON el.claim_id = bc.id AND el.evidence_type = 'article'
   JOIN news_articles na  ON na.id = el.article_id
   WHERE b.id = <brief_id>;
   ```
   Every row must resolve. Then re-fuse the same pair and confirm the brief flips to `stale`.

**Cost:** cents. A brief is ~2.5k input / ~800 output tokens; on Opus 4.8 that is ~3¢ per attempt, so the whole gate
lands around **$0.10–$0.50**. Run it on Opus — the entire point is proving *our* prompt and *our* Gate-4 validator hold
against *the model we ship*. A cheaper model passing tells you less.

### Item B — live GDELT fusion (needs a cooled-off IP)

**GDELT is currently rate-limiting this IP and it is not a five-second problem.** On 2026-07-13 the first live run fired
three requests in 28 seconds (see the bug in §4) and GDELT escalated: four subsequent well-spaced retries all took
`429`, and a single cheap diagnostic query minutes later got a **TLS handshake timeout** — the connection is being
dropped, not merely refused.

**Do not open with a burst.** Wait (hours, ideally overnight), then make **exactly one** call:

```bash
curl -s -w " -> HTTP %{http_code}\n" -X POST http://localhost:8000/aois/novo-progresso/fusion
# then WATCH, do not re-POST:
docker compose logs -f worker | grep -iE "HTTP/1.1|admitted|retry"
```

Success looks like `HTTP/1.1 200 OK` followed by `job …: N/M candidates admitted for novo-progresso`. If you see a
`429`, **stop** — the retry ladder (15/30/60 s) will play out on its own, and re-POSTing only deepens the penalty box.

Fuse **novo-progresso first**: it is the better story (the Mongabay deforestation coverage), and its window is the one
that proves the design correction. Then verify:

```sql
SELECT domain, title, seendate::date, gates_passed, query FROM news_articles ORDER BY seendate;
```
Every row should carry the terms and keywords that admitted it — the citations are auditable by construction.

Then **re-fuse the same AOI once** and confirm **zero duplicate rows** (replace-set idempotency, DoD #5's first half).

---

## 3. What IS already proven (do not redo it)

| Claim | Evidence |
|---|---|
| **The window correction is right, on real data** | novo-progresso's baseline was rebuilt live (24 detections, real pair `2023-07-30 → 2024-07-24`). Those DB rows through `FusionWindow.around()` → **`2023-06-30 … 2024-08-07`, admitting 4/4 demo articles**. The replaced after-anchored window → `2024-06-24 … 2024-08-07`, admitting **0/4**. |
| **Kill-switch, live, both ways** | `FUSION_ENABLED=false` → `POST …/fusion` returns **503 `fusion_disabled`**, checked *before* the AOI lookup (unknown slug → 503, not a leaked 404). Switched back on, the same slug → **404 `aoi_not_found`**. In the detection chain with it off, `overwatch.fuse` ran **0 times**. |
| **The money shot** | *"Amazon Prime Day deals announced"* **fires the toponym gate on "Amazon"** and the three-gate AND rejects it anyway. Unit test, green. |
| **Gate 4 — the observed/reported wall** | Journalism may not wear the clothes of sensing. Unit-tested from every angle. |
| **GDELT's failure path** | Exercised live: plaintext `429` parsed without crashing → `TransientFusionError` → 15/30/60 s backoff → task fails cleanly **without touching the job row or writing partial articles**. `fuse` is deliberately not a `JobTask` precisely so a GDELT outage cannot flip a succeeded detection job to `failed`. |
| **The compose env passthrough** | Proven by carrying `OVERWATCH_FUSION_ENABLED=false` into the container. The Anthropic key rides the identical mechanism, so it *will* arrive. |

**Both AOIs are primed.** `vizhinjam` (real pair `2021-02-12 → 2025-02-11`, 12 detections) and `novo-progresso` (real
pair `2023-07-30 → 2024-07-24`, 24 detections) each have a succeeded job — so you can fuse either immediately, with no
imagery work first.

---

## 4. The bug this session found — read it before you "fix" the throttle

**The GDELT rate limiter never fired.** `GdeltDocProvider` kept its throttle clock in an **instance** attribute, but
`get_news_provider()` builds a fresh provider on every task run and Celery re-runs the whole task body on every retry.
So each attempt started from a zeroed clock, computed a negative wait, and slept for nothing. Six-second throttle, dead
code in production. `retry_jitter` made it worse by drawing the countdown uniformly from `[0, backoff]` — it drew a
literal **"Retry in 0s"**.

Every test passed throughout, because they all replay fixtures through `FakeNewsProvider`, and **the throttle had zero
coverage**. It took a live run to surface.

Fixed in `585d27e`, in three layers — leave all three alone:
1. **The clock lives on the class.** GDELT limits per IP, so the limiter must be per *process*, not per object. Cold
   value is `-inf` so a cold clock never waits (`0.0` only ever worked by accident — `time.monotonic()` counts from
   system boot).
2. **`retry_backoff=15`, escalating 15/30/60, and `retry_jitter=False`.** Jitter exists to spread a thundering herd; we
   are one process behind one IP hitting a per-IP limit, so there is no herd and retrying *early* is strictly worse.
3. **Celery `rate_limit="10/m"` on the task.** The provider throttle is per process and Celery **forks** — the live
   retries landed on `ForkPoolWorker-7` and `-8`, each with its own copy of the clock. The node-level limit is the only
   one that spans them.

An autouse fixture resets the now-shared clock between tests; without it the suite serialized on real 6-second sleeps
and went from 11 s to 58 s.

---

## 5. Landmines

- **Never `docker volume prune` / `docker system prune --volumes`.** After `compose down` the containers are gone, so
  `overwatch_postgis_data` reads as *unattached* — a prune would silently destroy the AOIs and both scene pairs, and
  rebuilding novo-progresso's costs another live Sentinel-2 run. A plain `down` (no `-v`) preserves it.
- **GDELT stays angry.** See §2 Item B. One call. Then watch.
- **`sourcecountry` is a trap** — it is the *publisher's registration country*, not the story's location (Mongabay's
  Pará story returns `"Indonesia"`). Stored as provenance only. **Never use it as geography.**
- **Do not rebuild the geofence.** GDELT exposes no article geotag; GEO 2.0 404s; BigQuery/GGG is the *same* centroid-
  based geocoder, measured rejecting **100% of our true positives**. Gate 1 is a **toponym** gate and must never be
  called "spatial". Evidence in design §2.4/§2.4b and `CONTEXT.md`.
- **Titles omit the place name.** Zero of six Porto Alegre and zero of four Novo Progresso articles name their AOI in
  the title. Retrieval uses the **strict** term (full text, GDELT-side); the scorer corroborates with a **generous**
  list including regional names. Do not "tidy" `region_terms` down to just the city — you will score 0/4.
- **Verify the container restarted on the new image** before trusting a green run. A silent build failure once let the
  suite pass against stale code.

---

## 6. Definition of done (design §8) — current standing

| # | Item | Status |
|---|---|---|
| 1 | Real correlated articles cited for ≥1 AOI, every citation resolving to a `news_articles` row (SQL join) | ⛔ **Item A + B** |
| 2 | A deliberately irrelevant article demonstrably rejected | ✅ *"Amazon Prime Day"* — toponym fires, AND rejects |
| 3 | `FUSION_ENABLED` tested both ways | ✅ unit **and live** (503 + 0 fuse invocations in the chain) |
| 4 | Gate 4 rejects an article-only claim wearing observational framing | ✅ Task 8 |
| 5 | Re-run → zero duplicate rows; a validated brief on the re-fused pair flips to `stale` | 🟡 stale flip unit-proven; **live re-fuse needs Item B**, live flip needs **A + B** |

Once A and B land, Phase 5 is done and the branch is ready for review → merge → **Phase 6** (already fully planned in
`plans/2026-07-12-phase-6-frontend-arena.md`; its brief panel renders exactly the article citations Item A proves).
