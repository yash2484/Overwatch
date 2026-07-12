# Phase 6 Design — Frontend Arena

> **Status:** Approved by Yash in-session 2026-07-12 (brainstorm via `superpowers:brainstorming`,
> with `ui-ux-pro-max` and `impeccable` consulted for design direction).
> **Scope authority:** `plans/2026-07-03-mvp-roadmap.md` "Phase 6".
> **Goal:** the demo face. The evidence chain becomes something you can *click* — and the interface has to be good enough
> that a reviewer believes the engineering behind it.

---

## 1. The one-paragraph version

A single-screen operations console. A MapLibre GL basemap fills the viewport; deck.gl draws detection polygons over it;
a before/after swipe compares the two Sentinel-2 scenes; a right-hand panel holds the generated brief. Clicking a claim
highlights exactly the detections that back it — the client-side join that makes the trust architecture visible. Nothing
in the UI computes anything: it renders what the deterministic pipeline already decided.

---

## 2. Design direction

### 2.1 The reflex we are rejecting

Asked for "geospatial intelligence console, defense/gov-tech," both design skills returned the same thing: **matrix green
on OLED black, monospace everything, scanlines, HUD framing.** `ui-ux-pro-max` literally surfaced *"Cyberpunk UI"* and
*"Terminal CLI"* with `#00FF41` and `--scanline-opacity`.

That is the category's first training-data reflex — the definition of an AI tell. `impeccable`'s product register bans it
outright: in a tool, strangeness without purpose is the failure mode, and the bar is *earned familiarity*. A reviewer
fluent in Linear/Figma/Stripe would clock it instantly. **Rejected.**

The second-order reflex — *"defense tool that isn't cyberpunk, so: navy-and-slate enterprise dashboard"* — is also
rejected. Both are guessable from the category alone.

### 2.2 The scene sentence (what actually forces the theme)

> *An analyst holds two nearly-identical satellite images of a coastline side by side for minutes at a time, sliding
> between them to judge whether a smudge of grey is a new breakwater — while reading a paragraph of prose and checking,
> sentence by sentence, whether each claim is backed by a polygon.*

That sentence forces the answer, and it isn't "dark because tools look cool dark." **The imagery is the content.** A light
UI blows out the rasters and destroys the before/after comparison; pure black makes them glare. Photo editors, DaVinci,
and museum walls all land in the same place for the same reason: **a mid-dark, desaturated surround** is the only frame
that lets the picture be the brightest thing on screen.

### 2.3 Color strategy: **Restrained** (per `impeccable`'s product register floor)

The satellite imagery is already full-colour and full-chroma. The chrome must recede.

- **Surround:** graphite, not OLED black. Roughly `oklch(0.22 0.01 260)` for the app shell, one step lighter for panels.
  Tinted a hair toward the map's cool blues so it reads as one system, not chrome bolted onto a map.
- **Exactly one accent, carrying exactly one meaning: the evidence link.** A selected claim and the detection polygons
  that back it share it. Nothing else in the UI may use it. **The product's thesis becomes a colour rule** — that is the
  whole idea, and it is why the accent isn't decoration.
- **Accent hue: signal magenta**, ~`oklch(0.72 0.19 340)`. Chosen because it is **absent from land cover** — our three
  AOIs are ocean blue-teal, forest green, and turbid brown water. A magenta overlay can never be mistaken for terrain.
  (This is why cartographers reach for magenta for "not-of-the-earth" overlays.) It is also neither the matrix-green nor
  the Palantir-navy reflex.
- **Detection polygons carry change-type hue** (construction / clearing / water) at low-opacity fill with a solid stroke.
  Evidence selection is expressed as a **state, not a hue swap** — stroke weight plus a bright halo — so the change-type
  colour survives selection and we never convey meaning by colour alone.
- **Status vocabulary** (job/brief lifecycle): the standard semantic set — running / succeeded / failed / stale /
  rejected — desaturated, never full-chroma on inactive states.

### 2.4 Typography

**IBM Plex Sans + IBM Plex Mono.** Not Inter (the saturated default), not the Fira "dashboard template" the skill
suggested. Plex was drawn for technical and industrial contexts, and its mono sibling shares metrics with the sans — so a
column of areas lines up under its label without fighting.

- Sans carries the UI: labels, buttons, brief prose.
- Mono carries **data that must align or be compared**: areas (m²), confidence, dates, scene IDs, detection IDs, coords.
- `font-variant-numeric: tabular-nums` everywhere a number can change — the areas and confidences update on selection and
  must not reflow.
- Fixed rem scale (product register: no fluid clamp headings in a tool), ratio ~1.2.

### 2.5 Motion

Product register: **150–250 ms, motion conveys state, nothing decorative.** No page-load choreography — the app loads
into a task. CSS transitions only; deck.gl handles polygon highlight transitions natively. `prefers-reduced-motion`
honoured on every transition.

---

## 3. Stack

| Concern | Choice | Why |
|---|---|---|
| Map | **MapLibre GL** | basemap + raster scene layers. Already the roadmap's call. |
| Overlays | **deck.gl** via `MapboxOverlay` (interleaved) | `GeoJsonLayer` for detections; picking gives us click-to-select for free. |
| Styling | **Tailwind v4**, CSS-first `@theme`, **default palette deleted** | Utility speed *without* the templated look. Shipping Tailwind's stock `slate-500` ramp is exactly how a UI ends up looking generated. Our OKLCH tokens are the only palette. |
| Components | **None — ~6 bespoke** | panel, claim row, timeline scrubber, swipe handle, status pill, button. A component library would import a recognizable generic look and Radix deps we don't need. |
| Server state | **TanStack Query** | Owns the 2 s job/brief polling, backoff, and cache. This is precisely its job; hand-rolling it would be worse. |
| Client state | React context + `useReducer` | Selection state (`selectedClaimId`, `highlightedDetectionIds`, `swipePosition`) is small and local. No Redux, no Zustand. |
| Icons | **Lucide** (SVG) | One family, one stroke weight. Never emoji. |
| Motion | **CSS transitions only** | No Framer Motion: ~35 KB for what a 200 ms transition already does, and it invites the decorative motion the register bans. |
| Tests | **Vitest + React Testing Library** | The evidence-join and timeline reducers are pure → the TDD targets, same discipline as the detection engine. |

---

## 4. Backend work this phase needs (small, and it is a real gap)

The roadmap claims *"backend contract already in place; no backend rework expected."* That is true for click-to-evidence
(`GET /briefs/{id}` returns claims with detection IDs; the detections GeoJSON returns those IDs on features — a pure
client-side join). **It is not true for imagery.** Nothing serves scene rasters today; `render_rgb_png` exists only as a
Phase-1 CLI eyeball tool. Without this, there is no before/after slider — the demo's centrepiece.

**Pre-task (backend):**
1. `ingest_scene` also writes the true-colour PNG to a deterministic path: `./data/scenes/{aoi_slug}_{stac_id}.png`.
   Deterministic path ⇒ **no schema change**.
2. **`GET /scenes/{id}/image`** serves it; if the file is missing it renders on demand from the scene's stored window,
   caches, then serves. This backfills every scene ingested before this phase without a migration or a re-run.
3. **`GET /aois/{slug}/scenes`** — the timeline needs the scene list (id, captured_at, cloud_pct, usable_fraction).

The PNG is georeferenced for MapLibre by the scene's `window_geom` bounds → a raster `image` source with corner
coordinates. No tile server, no titiler, no new compose service.

---

## 5. Layout

One screen. No routing, no nav — a console, not a site.

```
┌────────────────────────────────────────────────────────────┬──────────────────┐
│  ▸ AOI switcher   ▸ job status   ▸ [Run detection]         │                  │
├────────────────────────────────────────────────────────────┤   INTELLIGENCE   │
│                                                            │      BRIEF       │
│                                                            │                  │
│                   MAP  (MapLibre + deck.gl)                │  headline        │
│                                                            │  ─────────       │
│                   before ◀───┃───▶ after     ← swipe       │  ▸ claim 1  [3]  │
│                   detection polygons                       │  ▸ claim 2  [1]  │
│                                                            │  ▸ claim 3  [—]  │
│                                                            │                  │
│                                                            │  ── sources ──   │
├────────────────────────────────────────────────────────────┤  ↗ The Hindu     │
│  scene timeline  ●───────●────────●─────●   before / after │  ↗ Mongabay      │
└────────────────────────────────────────────────────────────┴──────────────────┘
```

The map takes the space because the imagery is the content. The brief panel is a fixed-width column (not a floating
card — `impeccable`: cards are the lazy answer). The timeline is a rail, not a widget.

---

## 6. Click-to-evidence (the feature the whole project exists to demo)

**Claim → map.** Click a claim row → its `evidence.detection_ids` become `highlightedDetectionIds` → deck.gl restyles
those polygons (magenta halo, heavier stroke) → the map eases to their combined bounds. The claim row shows its evidence
count (`[3]`) so a claim with no detections (`[—]` — a `context` claim) is visibly different *before* you click it.

**Map → claim.** Click a polygon → the claims citing that detection highlight in the panel and scroll into view. The join
runs both directions; it is the same index.

**Article citations** open the source in a new tab, and are visually distinct from detection evidence — because they *are*
different. A `reported` claim is marked as such in the panel. **The observed/reported wall from Phase 5 is rendered, not
just enforced in the database.** This is the demo's best 10 seconds.

The join itself is a **pure function** — `buildEvidenceIndex(brief, detections) → { claimId → detectionIds, detectionId →
claimIds }` — and therefore the primary Vitest target.

---

## 7. States

Every one of these is a real state the backend can actually produce, so every one gets built:

| State | What the user sees |
|---|---|
| **Empty** (no job yet) | Map at AOI bounds, panel teaches the flow: "Run detection to generate a brief." Not "nothing here." |
| **Job running** | Timeline rail shows the stage (`ingest_before → ingest_after → detect → fuse`). Skeleton in the panel, not a spinner. |
| **Job failed** | The structured error from `jobs.error` (it is JSONB and already carries a code + message), with a retry. |
| **Brief generating** | Skeleton claim rows. |
| **Brief validated** | The normal state. |
| **Brief rejected** | **Shown, not hidden** — with its per-attempt violations. A rejected brief is an audit artifact and one of the most persuasive things in the demo: *the validator caught the model.* |
| **Brief stale** | Banner: detections were re-run; this brief's evidence no longer matches. Offer regeneration. |
| **No detections** | Honest empty result — the engine ran and found nothing. Not an error. |
| **No articles** | The brief simply has no sources section (Phase 5 §4.2: better to cite nothing). |

---

## 8. Gate (definition of done)

1. The **<2-minute demo works end-to-end for all three showcase AOIs**: load → swipe before/after → see polygons →
   read brief → click a claim → watch its detections light up → click a source.
2. Click-to-evidence joins correctly in **both directions**, proven by Vitest tests over the pure index.
3. A **rejected** brief renders with its violations; a **stale** brief renders its banner.
4. `prefers-reduced-motion` honoured; keyboard-navigable claim list; focus rings intact.
5. Body-text contrast ≥ 4.5:1 against the graphite surround (verified, not assumed).

## 9. Out of scope (v0.1)

AOI **draw** tool — the roadmap lists it, but all three showcase AOIs are seeded and the demo never draws one; it is
scope that serves no gate. (The AOI *switcher* ships; drawing does not.) Also out: mobile layout (this is a desktop
analyst console — it degrades gracefully, it does not reflow to a phone), multi-brief history browsing, dark/light toggle
(§2.2 — the theme is a functional requirement, not a preference).
