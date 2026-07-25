# Handover — Phase 5, the last two verification items

> **Written:** 2026-07-13. **Revised 2026-07-14** after a live run overturned Item B's diagnosis — read §0 first.
> **Branch:** `phase-5-osint-fusion` — clean tree, all work committed, **289 tests passing**.
> **State:** **All 12 tasks are BUILT.** The verification gate is *partially* done. Two items remain: one needs an API
> key, one is an **open bug** — live GDELT returns **zero articles** for novo-progresso and we do not yet know why.
> **Supersedes:** `HANDOVER-phase-5.md` (that one got you to Task 9; Tasks 9–12 are now done).

---

## 0. READ THIS FIRST — the IP is blocked for ≥12 days now, not just rate-limited (2026-07-26)

**Newest evidence first.** On 2026-07-25, after **~12 days of zero GDELT traffic from this IP**, a single fuse call
(vizhinjam — the decisive test this doc itself prescribes) got **`429` on every one of 4 attempts**: the initial
request plus the full 15/30/60 s retry ladder, all rejected, task failed cleanly. Our retry policy is not the problem —
it executed exactly as designed (correct backoff, zero rows written, job row untouched, `585d27e`'s fix confirmed
working). **The problem is GDELT still rejecting the very first request after nearly two weeks of silence.** That is
no longer "rate limited," it's "this IP is blocked," on a timescale far longer than the ~75 s the original spike
observed. Do not retry again today — a 5th attempt right now is not new information.

**What this means for the two open hypotheses below:** the 2026-07-14 result (`200 OK`, 0/0 articles for
novo-progresso) predates this. We do not know if that AOI's query is genuinely too strict, because **we can no longer
get a request through at all to re-test it.** The decisive test (fuse vizhinjam) could not run on 2026-07-25 — it hit
the block before ever reaching the point of discriminating hypothesis (a) vs (b).

**Next attempt, whenever it happens, should not be from this IP.** Two weeks of silence not clearing it suggests a
long-duration or manual block, not an automatic sliding window. Try a genuinely different network path — not just a
mobile hotspot on the same carrier/region, but ideally a different ISP entirely, or a cloud VPS `curl` from outside
India — before spending any more of this IP's attempts. If a different network's first call also gets `429`
immediately, that would be new and important information (points at something GDELT-side unrelated to this specific
IP, e.g. this ASN or country range). If it succeeds, resume exactly at "The decisive test" below.

---

### Older context (2026-07-14) — kept for the reasoning trail, superseded by the block above

The 2026-07-13 handover said Item B just needed a cooled-off IP. **That was wrong** — at least, it stopped being
sufficient. On 2026-07-14 the IP *was* cold (~24 h since the last request) and the first call went through clean:

```
HTTP/1.1 200 OK   query="Novo Progresso" (theme:ENV_DEFORESTATION OR theme:ENV_FORESTRY)
                  startdatetime=20230630140435  enddatetime=20240807140432
job ee2e5ec3…: 0/0 candidates admitted for novo-progresso
Task overwatch.fuse succeeded in 15.99s: 0
```

**`200 OK` and zero articles.** Not a 429. Not a crash. GDELT simply returned nothing. Two things this rules out:

- **It is not the rate limiter.** The call succeeded. Waiting longer does not fix a successful call that returns no data.
- **It is not a GDELT coverage limit.** GDELT's own DOC 2.0 *debut* page still says `STARTDATETIME` **"must be within the
  last 3 months"** — **that page is stale.** The later ["1.5 Year Searching"](https://blog.gdeltproject.org/doc-2-0-updates-1-5-year-searching-and-updated-mobile-interface/)
  post says the rolling cutoff was *"permanently replaced"* by a fixed **Jan 1 2017** start. And we have proof in-repo:
  `backend/tests/fixtures/gdelt/vizhinjam_2024.json` is a **verbatim DOC artlist capture** (it carries the DOC-only
  fields `url_mobile` / `socialimage` / `sourcecountry`, and a Malayalam-script title) of **June–July 2024** articles,
  pulled during the 2026-07-12 spike. DOC returns articles **two years back**. Do not re-litigate this.

So `0/0` is a **real, open bug.** The two live hypotheses:

- **(a) The forest query is too strict.** `"Novo Progresso" (theme:ENV_DEFORESTATION OR theme:ENV_FORESTRY)` is a
  conjunction. If the Mongabay Aug-2023 pieces don't carry those two GKG themes, GDELT correctly returns nothing and
  our *retrieval layer* — not the scorer — is what's rejecting the demo corpus.
- **(b) GDELT is serving empty `200`s to a penalised IP.** Possible but unproven; a plain `{}` body is also what a
  genuine zero-result looks like.

### The decisive test — do this FIRST, one call, on a cold IP

**Fuse `vizhinjam`, not `novo-progresso`.** It is the only AOI whose correct answer we already know, because the spike
captured it. Verified offline on 2026-07-14: its live window computes to **`2023-12-09 → 2025-02-25`**, and **all four**
fixture articles fall inside it.

```bash
curl -s -w " -> HTTP %{http_code}\n" -X POST http://localhost:8000/aois/vizhinjam/fusion
docker compose logs -f worker | grep -iE "HTTP/1.1|admitted|retry"
```

Expect ≥4 admitted, including `thehindu.com` (2024-06-15), `thehindu.com` (2024-06-20), `mathrubhumi.com` (2024-07-06),
`thehindubusinessline.com` (2024-07-15).

- **Vizhinjam returns them → the live pipeline works.** Hypothesis (a) is confirmed and the bug is scoped to the *forest
  preset's theme filter*. Next step: bisect the novo query — try bare `"Novo Progresso"` with no theme clause, then add
  themes back one at a time, to find which (if any) theme the Mongabay articles actually carry. **Space every call ≥60 s.**
- **Vizhinjam ALSO returns 0 → hypothesis (b).** The problem is the IP/transport, not our code. Stop and re-test from a
  different network before touching a line of source.

### Rate-limit discipline — I broke it, don't repeat it

After the clean call I fired two diagnostics ~25 s apart. GDELT `429`'d the second with a **plaintext** body:

> *"Please limit requests to one every 5 seconds or contact kalev.leetaru5@gmail.com for larger queries."*

Three requests in ~2 minutes was enough to re-trigger the penalty even though each was individually inside the documented
5 s ask. **One call. Then watch the worker. Do not re-POST.**

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

### Item A — the SQL join proof + the live stale flip (needs a WORKING payment method, see below)

This is DoD #1 and the live half of #5: *real articles cited by a real, model-authored, validated brief, with every
citation resolving to a `news_articles` row.*

**⚠️ 2026-07-26 update — the key exists, the money does not. Read this before repeating any of this diagnosis.**

A key was created and tested end-to-end this session:
- Env passthrough confirmed working (`settings.anthropic_api_key` → `True`, correct `sk-ant-...` prefix).
- A real `client.messages.create(...)` call was made against `claude-opus-4-8`.
- It returned **`400 invalid_request_error`: "Your credit balance is too low to access the Anthropic API."**

That is not an auth failure — the key, the client, and the network path are all proven correct. **The org's balance is
genuinely $0.00, not a dashboard display quirk.** The blocker is 100% upstream of this codebase: the org
("Yash's Individual Org — API plan," console.anthropic.com) has never successfully received a payment.

**Root cause, now well-evidenced (not fully certain, but strong):** the card is **RuPay** (ICICI Bank, RuPay-network,
`6528 XXXX XXXX 8007` — matches the earlier "Discover ending 8007" failure email; RuPay routes internationally via a
Discover/Diners partnership). **RuPay generally does not support one-time international card-not-present (online)
transactions**, even with the phone-app "international transactions" toggle on (that toggle typically governs
ATM/POS abroad, not this transaction class). Every attempt — 2 cards, 2 networks, incognito, both the plan's $5
credit-purchase modal AND the Console's native "Add funds" — reached OTP for a literal **$0.00** authorization and
never proceeded to the real charge. That is consistent with RuPay either not routing the real-value authorization at
all, or the issuer only ever completing the $0 verification step for this transaction class.

The one fact that doesn't fit a pure "broken account" theory: **the same card's Pro subscription renews successfully
every month via "Link by Stripe."** That is very plausibly explained by recurring/merchant-initiated billing being a
*different* transaction type than a fresh customer-initiated one-time charge — RuPay may permit the former (a
pre-registered recurring mandate) while blocking the latter outright. Same card, same bank, genuinely different rules.

**What actually unblocks this — in priority order:**
1. **A Visa or Mastercard card, any bank, for one $5–6 charge.** Neither network carries RuPay's international-CNP
   restriction. This is the one fix likely to just work. Doesn't have to be the user's own card.
2. **A brand-new Anthropic account** (different email) that might carry free trial credit — untested, but costs
   nothing to check and doesn't depend on solving the RuPay problem at all.
3. **Anthropic support**, with the evidence above already assembled — but temper expectations. If the diagnosis is
   right, this is a card-network limitation, not something in Anthropic's/Stripe's control to route around.

**Do NOT re-run the DNS/network/incognito/kill-switch diagnostics again — all already ruled out, see the payment
troubleshooting in this session's transcript if the reasoning needs re-deriving.** The one open, useful test — if a
Visa/Mastercard becomes available — is simply: does *that* card's OTP show the real amount, not $0.00. If yes, this
was RuPay all along and Item A is unblocked immediately using the exact steps below.

---

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

### Item B — live GDELT fusion — ⚠️ **OPEN BUG, see §0**

**Superseded by §0.** The original diagnosis ("just needs a cooled-off IP") was disproven on 2026-07-14: the IP *was*
cold, the call returned `200 OK`, and GDELT still gave us **zero articles** for novo-progresso.

**Do not open by fusing novo-progresso** — a zero there is ambiguous and tells you nothing new. Run the **vizhinjam
decisive test in §0** instead: it is the one AOI whose correct answer we already know (4 captured articles, all inside
its live window). That single call discriminates between "our forest query is too strict" and "GDELT is stiffing this IP".

Once fusion actually returns rows, the remaining verification is unchanged:

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
| 1 | Real correlated articles cited for ≥1 AOI, every citation resolving to a `news_articles` row (SQL join) | ⛔ **blocked on the §0 bug** — live fusion currently retrieves **0 articles**, so there is nothing to cite yet |
| 2 | A deliberately irrelevant article demonstrably rejected | ✅ *"Amazon Prime Day"* — toponym fires, AND rejects |
| 3 | `FUSION_ENABLED` tested both ways | ✅ unit **and live** (503 + 0 fuse invocations in the chain) |
| 4 | Gate 4 rejects an article-only claim wearing observational framing | ✅ Task 8 |
| 5 | Re-run → zero duplicate rows; a validated brief on the re-fused pair flips to `stale` | 🟡 stale flip unit-proven; both live halves blocked on the §0 bug |

**Phase 5 is further from done than the 2026-07-13 handover implied.** DoD #1 is the load-bearing claim of the whole
phase — *real articles, really cited* — and right now the live retrieval path returns nothing. Everything downstream of
it (#1, the live half of #5, and Phase 6's brief panel, which renders exactly these citations) sits behind that.
The §0 vizhinjam test is the one thing that moves it.

Verified again on 2026-07-14 (so you can trust the baseline): **289 passed**, `ruff check` clean, `alembic current` =
`0004 (head)`, `FUSION_ENABLED=True`, `news_articles` = **0 rows**, `settings.anthropic_api_key` = **False** (no `.env`).
