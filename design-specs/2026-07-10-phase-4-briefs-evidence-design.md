# Phase 4 Design — Briefs + Evidence Chain

> **Status:** Approved by Yash in-session 2026-07-10 (brainstorm via `superpowers:brainstorming`).
> **Scope authority:** `plans/2026-07-03-mvp-roadmap.md` "Phase 4" heading; data model authority is design-spec §4 (`design-specs/2026-07-02-overwatch-mvp-design.md`), extended by decisions 3 and 6 below.
> **Goal:** the trust architecture — an LLM narrates over stored detections only, and a deterministic validator proves every claim traces to real rows.

---

## 1. Decisions resolved (2026-07-10 brainstorm)

1. **Trigger model: briefs own their lifecycle.** `POST /aois/{slug}/briefs` → 202 + `brief_id`; a Celery task generates; poll `GET /briefs/{id}`. Status lives on the `briefs` row (`generating → validated | rejected | failed`, plus `stale` — decision 6). No changes to the `jobs` table; no auto-generation after detect (can be added later behind a flag without rework).
2. **Output contract: structured claims via the SDK's typed parse.** The LLM is forced through a JSON schema: it returns `{headline, claims: [{text, claim_type, evidence: [detection_ids]}]}`. The brief IS the ordered claim list. Implementation uses `client.messages.parse(..., output_format=BriefDraft)` (Pydantic v2 model, SDK-validated) — no prose parsing, no hand-rolled tool schemas. Malformed structure fails at the API boundary, not in our code.
3. **Validator depth: links + numeric consistency** (upgrade over the roadmap's linkage-only wording). Three deterministic gates — see §4. "The validator checks the numbers, not just the links."
4. **Brief scope: pair-scoped, append-only history.** A brief narrates one `(aoi, before_scene, after_scene)` pair — by default the latest succeeded job's pair, overridable in the POST body. Each POST creates a new brief row (with up to 3 internal generation attempts); old rows are kept. Rejected briefs are first-class audit artifacts, surfaced with their violations.
5. **No sampling-parameter determinism.** `temperature`/`top_p`/`top_k` no longer exist on current Anthropic models (400 if sent). Reproducibility is the validator's job; the LLM layer is narration only. (Corrects PROJECT.md's "determinism option" as applied to this layer.)
6. **Staleness on detection replace-set** (gap found in the roadmap). Phase 3's detection persistence deletes + reinserts rows on re-run, so a validated brief's evidence links would cascade away — leaving a "validated" brief with dangling claims. Fix: `replace_detections` flips `validated` briefs on that pair to `stale` in the same transaction. Invariant preserved: **validated ⇒ every link resolves**.
7. **Phase 5 future-proofing baked into the schema.** `brief_claims.claim_type` takes the full enum now (`observed | context | reported | mixed`); the Phase 4 validator rejects `reported`/`mixed` (no articles exist yet). `evidence_links` is polymorphic by `evidence_type` (`detection | article`) with explicit per-type FK columns; `article_id` arrives as an additive Phase 5 migration. Phase 5's observed-vs-reported rule becomes validator Gate 4 — additive, no migration.
8. **Execution: mixed mode.** Subagent-driven sequential spine for shared-file tasks; parallel agents for the disjoint pure-module cluster (validator / generator+fake / prompt). See §8.

## 2. Data model (alembic migration 0003, additive; existing tables untouched — one repo function changes)

### `briefs`

| column | type | notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `aoi_id` | BIGINT FK `aois` ON DELETE CASCADE, NOT NULL | |
| `before_scene_id` / `after_scene_id` | BIGINT FK `scenes`, NOT NULL | the narrated pair |
| `status` | TEXT NOT NULL | `generating \| validated \| rejected \| failed \| stale` |
| `attempts` | INT NOT NULL DEFAULT 0 | generation attempts consumed (≤ `brief_max_attempts`) |
| `headline` | TEXT NULL | from the validated draft |
| `model` | TEXT NULL | model ID that produced the final attempt (audit) |
| `usage` | JSONB NOT NULL DEFAULT '{}' | accumulated token counts across attempts (audit) |
| `violations` | JSONB NULL | per-attempt validator output — why attempts failed / why rejected |
| `error` | JSONB NULL | structured transport-failure payload (same shape as `jobs.error`) |
| `created_at` / `updated_at` | timestamptz | |

Index `(aoi_id, created_at DESC)` (latest-validated lookup) and `(aoi_id, before_scene_id, after_scene_id)` (stale-marking).

### `brief_claims`

| column | type | notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `brief_id` | BIGINT FK `briefs` ON DELETE CASCADE, NOT NULL | |
| `seq` | INT NOT NULL | render order; UNIQUE `(brief_id, seq)` |
| `text` | TEXT NOT NULL | |
| `claim_type` | TEXT NOT NULL | `observed \| context \| reported \| mixed` (Phase 4 emits/accepts only the first two) |

### `evidence_links`

| column | type | notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `claim_id` | BIGINT FK `brief_claims` ON DELETE CASCADE, NOT NULL | |
| `evidence_type` | TEXT NOT NULL | `detection \| article` |
| `detection_id` | BIGINT FK `detections` ON DELETE CASCADE, NULL | CHECK: `evidence_type = 'detection' → detection_id IS NOT NULL` |

Claims and links are persisted **only for validated briefs** (a rejected brief keeps its last draft inside `violations` detail for audit; failed/generating briefs have neither).

**Repo change outside the new tables:** `replace_detections(aoi, pair)` additionally runs `UPDATE briefs SET status='stale' WHERE aoi_id=... AND before_scene_id=... AND after_scene_id=... AND status='validated'` in the same transaction (decision 6).

## 3. BriefGenerator (`overwatch/briefs/`)

- `models.py` — Pydantic v2: `ClaimDraft {text, claim_type, evidence: list[int]}`, `BriefDraft {headline, claims}`, `Violation {code, claim_seq | None, message, detail}`, `BriefRequest` (AOI meta, pair dates/ids, detection rows, aggregate stats).
- `prompt.py` — pure builder: system + user prompt from `BriefRequest`. Detections capped at `Settings.brief_max_prompt_detections` (default 50, by `area_m2` desc) with aggregate stats always included (count, total area, per-change-type breakdown); truncation is logged, never silent. Instructs: cite detections by id; `context` claims allowed but must carry no quantities.
- `generator.py` — `BriefGenerator` Protocol: `generate(request, feedback: list[Violation] | None) -> BriefGeneration` (draft + model id + usage). Two implementations:
  - `AnthropicBriefGenerator` — sync `anthropic` client (task is sync Celery), `client.messages.parse(model=settings.anthropic_model, max_tokens=16000, thinking={"type": "adaptive"}, output_format=BriefDraft, messages=...)`. On regeneration, prior draft + serialized violations are appended as assistant/user turns (structured feedback). SDK default retries (2) handle blips; typed exceptions map to transient/permanent (§5).
  - `FakeBriefGenerator` — scripted sequence of drafts for tests; records received feedback. Zero network; CI never needs a key.
- New `Settings` fields: `anthropic_model: str = "claude-opus-4-8"`, `brief_max_attempts: int = 3`, `brief_max_prompt_detections: int = 50`. (`anthropic_api_key` already exists; the real key enters `.env` at the live gate — user provides, never committed.)

## 4. Validator (`overwatch/briefs/validator.py` — pure, the anti-hallucination gate)

Input: `BriefDraft` + the pair's detection rows (id, `area_m2`, dates come from scenes). Output: `list[Violation]` (empty = valid).

| gate | rule | violation code |
|---|---|---|
| structural | ≥1 claim; non-blank texts; headline present; `claim_type ∈ {observed, context}` (Phase 4) | `empty_brief`, `blank_claim`, `unsupported_claim_type` |
| 1 — linkage | every `observed` claim has ≥1 evidence id, and every id belongs to this brief's exact (aoi, pair) detection set | `unlinked_claim`, `unknown_evidence_id` |
| 2 — context hygiene | `context` claims contain no detection-derived quantities (regex: m²/km²/ha, percentages, ISO/wordy dates) | `quantified_context_claim` |
| 3 — numeric consistency | any area figure quoted in an observed claim matches the summed `area_m2` of its linked detections within ±10%; any date in an observed claim matches the pair's capture dates | `area_mismatch`, `date_mismatch` |

Violations are serialized into the regeneration feedback verbatim; after `brief_max_attempts` failures the brief is `rejected` with the full per-attempt violation history stored — never silently dropped (design-spec §4 requirement).

## 5. Celery task + API surface

**Task `generate_brief(brief_id)`** (queue as Phase 3 tasks): load brief (must be `generating`) + AOI + pair + detections → loop ≤ `brief_max_attempts`: generate (with prior violations as feedback) → validate → on pass persist claims+links, `status=validated`, store `model`/`usage` → on violations record + retry. Exhausted → `rejected`. Transport errors: `RateLimitError` / 5xx `APIStatusError` / `APIConnectionError` → Celery autoretry with backoff (attempts visible while polling, mirroring Phase 3); permanent (`AuthenticationError`, 4xx) → `failed` with structured `error`. Tests exercise retries via `task.apply(...)` (CONTEXT.md: `retry()` is a no-op on direct calls).

**API** (same error-envelope conventions as Phase 3):

| endpoint | behavior |
|---|---|
| `POST /aois/{slug}/briefs` | body `{before_scene_id?, after_scene_id?}`; defaults to `latest_succeeded_job`'s pair. 202 `{brief_id}`. Guards: `404 aoi_not_found`; `409 no_baseline_run` (no succeeded job and no explicit pair); `422 briefs_unconfigured` (no API key — fail at the API, not in the worker). |
| `GET /briefs/{id}` | full brief: status, attempts, headline, claims (with evidence detection ids), violations (when rejected), model/usage, pair ids. `404 brief_not_found`. |
| `GET /aois/{slug}/brief` | latest `validated` brief for the AOI; `404 no_validated_brief`. |

**Phase 6 pre-wiring (zero backend rework later):** claims carry `detection_id`s; the existing GeoJSON detections endpoint already returns those ids on features — click-to-evidence is a client-side join.

## 6. Testing strategy (TDD, red→green per task)

- **Pure units:** validator — one negative-test family per gate plus a passing draft; prompt builder — truncation, stats, feedback rendering; Pydantic models — schema round-trip.
- **Generator loop:** with `FakeBriefGenerator` — first-try pass; violation→feedback→pass on attempt 2 (asserts feedback content); 3 strikes → rejected with per-attempt violations; the roadmap's headline negative test (deliberately unlinked claim demonstrably rejected) lives here, deterministic.
- **DB:** brief repo lifecycle; claims/links persisted only on validated; stale-marking on `replace_detections`; cascade behavior. Fixtures follow the Phase 3 teardown-ordering lesson (CONTEXT.md).
- **Task:** `.apply()` with `FakeBriefGenerator` injected; transport-error path with a mock anthropic client raising typed exceptions (transient → attempts climb → `task_failed`-style; permanent → fast `failed`).
- **API:** submit/poll/latest happy paths + every guard code.
- **CI:** never needs the Anthropic key (Fake everywhere). Live-API runs are manual verification only (MVP design-spec §8 rule).

## 7. Verification gate (live, in-container, evidence appended to the plan)

1. Full suite (117 + new) + `ruff check` + `ruff format --check` green in-container.
2. `alembic upgrade head` → 0003; idempotent seeder unaffected.
3. Real key in `.env` (user-provided) → `POST /aois/vizhinjam/briefs` → poll → `validated`; SQL join proves **every evidence link resolves to a detection of the exact pair**; claims render coherently (eyeball).
4. Rejected path surfaced: a rejected brief row (from the Fake-driven test DB or a live forced run) retrievable via `GET /briefs/{id}` with violations visible.
5. Staleness: re-run the detection job for the same pair → prior validated brief flips to `stale`; new brief can be generated against the fresh rows.
6. Hygiene: `git grep` proves no key material in the tree; `.env` untracked.

## 8. Execution strategy (mixed mode, approved)

Branch `phase-4-briefs-evidence`. **Prerequisite: Docker Desktop running** (in-container TDD; it does not auto-start on this machine).

- **Stage 1 — sequential spine** (shared files: `models.py`, migration, `db/`): migration 0003 + ORM → brief repository (+ stale-marking in `replace_detections`).
- **Stage 2 — parallel lanes** (disjoint new files, 3 concurrent agents): validator + tests ∥ generator + Fake + tests ∥ prompt builder + tests. All depend only on Stage 1's Pydantic/ORM types.
- **Stage 3 — sequential spine** (shared files: `workers/`, `api/`, compose): Celery task (composes Stage 2) → API endpoints + guards → live gate + docs.

Review gate after each stage (`superpowers:requesting-code-review` before merge).

## 9. Out of scope (Phase 4)

- `news_articles`, GDELT, reported-speech validation (Phase 5 — Gate 4 slot reserved).
- Auto-brief-after-detect chain extension (possible later behind a flag).
- Frontend brief panel (Phase 6; contract pre-wired in §5).
- Forest temporal-persistence check (backlog, unchanged).
