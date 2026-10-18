---
type: contract
tags: [outset, manifest, hub, calendar, schedule, lanes, providers, federation]
---

# The App Manifest

**Manifest version 1** · 2026-09-05 · machine half: `outset_manifest.py`

Every Outset app publishes one document, `GET api/manifest`, that says what
it is, how it signs people in, what it runs on a timer, which model lanes it
spends, and where its call log is. The Hub reads it on registration and
re-reads it on a schedule; Atlas reads it to draw the same calendar. Adding a
module to the Hub is pointing the Hub at the app.

The Feed is the reference implementation (`feed/manifest.py`, served by
`feed/api/manifest.py`). The Ledger's router (`ai_client.py`) is the reference
for `lanes` and provider names.

## The rules the shape encodes

These come from the calendar build plan brief (2026-09-05) and are not
negotiable in any manifest version.

1. **Standalone first.** An app publishes its manifest whether or not anything
   reads it. Nothing in the manifest requires a Hub, a peer, a broker or Atlas.
2. **Per-app settings are authoritative.** The manifest *describes* a block or
   a lane. The app's own settings own it. `run_endpoint` and `toggle_endpoint`
   forward a person's request to the app; the app decides. The Hub never owns
   an app's state.
3. **Never widen a schedule.** A block appears in the manifest before it ever
   runs. There is no field that means "run more often than the app does".
4. **Recommend, never auto-download.** A lane names the model it runs; the
   Hub's advisor may suggest another; a human pulls it.
5. **No legacy names.** The module, the endpoint and this document
   carry the Outset name.
6. **The anonymous body leaks no operational shape.** Same rule as
   `/api/status`: chain hours, model names, last results and error text are
   for identified operators only.

## Who reads what

| Section | Carries | Consumed by |
|---|---|---|
| identity | `manifest_version`, `app`, `name`, `version` | everything |
| `card` | where the summary and health live; lab URL; production URL; icon; accent | Hub cards. **Cards keep reading `summary` from `api/status`** (the hub-card contract); the manifest only points at it and adds the production URL |
| `auth` | `mode`, whether the app honours the Hub's signed claims | Hub federation matrix: pass-through vs "this app has its own login" |
| `schedule` | active window, chains, blocks with cadence + last/next run, the Run-now and on/off endpoints | Calendar (Hub + Atlas); Run now and on/off forwarding |
| `lanes` | each model-using job class: what it needs, provider + model it runs now | Hub providers module pre-populates; the app's own Models panel edits |
| `usage` | the per-call log endpoint, or `null` until the app keeps one | Calendar "actual" overlay, budgets, broker metrics (step 2 fills this) |

## Serving it

* Path: `api/manifest`, `GET`, JSON. Relative, like every other path
  (CONTRACT rule 2) — the Hub joins it to the URL it registered.
* **Gated sections.** `schedule`, `lanes` and `usage` are served only to a
  caller the app identifies as an operator: its own admin session, its
  service token, or (for `ad-builtin` apps) the Hub's signed claims. Anyone
  else gets identity + `card` + `auth` and a `gated: [...]` list naming what
  was withheld. `outset_manifest.public_view()` produces that shape.
* Re-read cadence is the Hub's business; an app must be able to serve the
  manifest cheaply (the Feed reads one JSON state file and its config).

## Shape

```json
{
  "manifest_version": 1,
  "app": "feed",
  "name": "The Feed",
  "version": "2.0.0",

  "card": {
    "summary_endpoint": "api/status",
    "health_endpoint": "api/status",
    "lab_url": "http://internal-host.home.example:5003/",
    "production_url": null,
    "icon": "broadcast-pin",
    "accent_color": "#83a598"
  },

  "auth": {
    "mode": "own-login",
    "honours_hub_claims": false,
    "federated": false,
    "accounts": "local"
  },

  "schedule": {
    "tz": "America/Chicago",
    "active_window": {"from": "08:00", "to": "20:00"},
    "run_endpoint": "api/schedule/run",
    "toggle_endpoint": "api/schedule/toggle",
    "chains": [
      {"key": "daily", "label": "The daily chain",
       "cadence": {"kind": "daily", "at": "08:00", "tz": "America/Chicago", ...},
       "blocks": ["ingest", "briefings", "score", "benchmarks"],
       "last_run": "2026-09-05T13:00:02+00:00", "ran": ["ingest", "briefings", "score"],
       "next_run": "2026-09-06T13:00:00+00:00", "pending": false}
    ],
    "blocks": [
      {"key": "score", "label": "Score the public desks", "what": "…",
       "lane": "scoring", "chain": "daily", "cadence": null, "condition": null,
       "enabled": true, "last_run": "…", "ok": true, "result": "…", "ms": 41200,
       "next_run": "2026-09-06T13:00:00+00:00", "pending": false,
       "budget": {"calls_per_run": 8}, "hold_min": null},
      {"key": "images", "label": "Image cache", "what": "…", "lane": null,
       "chain": null,
       "cadence": {"kind": "interval", "every_min": 10, "within_window": true, ...},
       ...}
    ],
    "now": "2026-09-05T15:04:05+00:00"
  },

  "lanes": [
    {"key": "scoring", "label": "Scoring", "what": "…",
     "needs": {"min_ctx": 16384, "speed": "batch", "json": true},
     "provider": "local", "model": "qwen3:14b", "ctx": 32768,
     "override": true, "per_user": false}
  ],

  "usage": {"endpoint": null, "note": "No per-call log yet (core call log, step 2)."}
}
```

### `card`

| Field | Meaning |
|---|---|
| `summary_endpoint` | where the card's `summary` comes from — `api/status` unless the app has a reason |
| `health_endpoint` | what a monitor probes; `api/status` is exempt from auth by contract |
| `lab_url` | the instance the card points at while the app is lab-only; deployment config, never code (`BROADSHEET_LAB_URL` in the Feed) |
| `production_url` | set when the app goes production; the card then points here and the LAN copy is dev/rollback (`BROADSHEET_PRODUCTION_URL`). **Which apps are production is the owner's call** — the manifest carries it, it does not decide it |
| `icon`, `accent_color` | as in `/api/status.card` |

### `auth`

| `mode` | Meaning | Hub behaviour |
|---|---|---|
| `ad-builtin` | the app authenticates against a directory itself (hybrid local + AD counts) | with `honours_hub_claims: true` the app accepts the signed `X-Hub-Auth` claims and never re-prompts: **federated** |
| `own-login` | the app has its own accounts and login screen | the Hub links to it; a person signs in there. Never federated, never pretended |

`federated` is derived (`ad-builtin` **and** honours claims) so the matrix
reads off the manifest. The Hub itself is AD-only everywhere; federation is
an addition when the Hub is present, never a dependency.

Today: a sibling app `ad-builtin`/honours (hybrid contract); Ledger `ad-builtin`
(ldap backend; honours signed claims in hub mode); Atlas `ad-builtin`
(hybrid); **Feed `own-login`** (local accounts + MFA; `resolve_identity`
consults no hub headers by design — the site is public and header trust
would be forgeable).

### `schedule`

* `tz` — the zone the app's own clock runs in. `active_window` — the local
  wall-clock window the app's worker keeps (blank ends = around the clock).
* `run_endpoint` — `POST {"block": "<key>"}`; a chain key is accepted too.
  Queues a manual run; the app runs it on its next tick, window or not, because
  a person asked.
* `toggle_endpoint` — `POST {"block": "<key>", "enabled": bool}`. Only blocks
  the app lets a person switch (the Feed: chain blocks; not the image cache).
* `chains[]` — an ordered run of blocks on one timer. Blocks with `chain` set
  inherit its cadence and carry `cadence: null`.
* `blocks[]` — one entry per job the worker knows. `lane` names the model
  lane it spends (`null` = no model calls, which is what lets a calendar tell
  a GPU block from a network one). `condition` is prose for a block that runs
  inside its chain only sometimes ("older than 7 days"). `budget` is prose-
  free: `{"calls_per_run": n}` when the app caps it. `hold_min` is how long a
  run typically keeps the model (Atlas rites' `hold`) — `null` when unknown;
  `ms` is what the last run actually took.
* `next_run` — aware ISO instant, or `null` for interval / on-request blocks.

#### `cadence`

One vocabulary for the Feed's chain, the Ledger's APScheduler entries and
Atlas rites. Every cadence has every key; only the kind's own are meaningful.

| `kind` | Uses | Maps from |
|---|---|---|
| `daily` | `at` HH:MM, `tz`, optional `days` ("Mon-Fri") | Feed `chain_at`; Ledger `daily`/`overnight`/`market-*` (→ `days: Mon-Fri`); Atlas `daily` |
| `weekly` | `day`, `at`, `tz` | Feed `weekly_rollup_at` (Sun, UTC); Ledger `weekly*`; Atlas `weekly` |
| `interval` | `every_min`, `within_window` | Feed image cache; Ledger `15min`/`30min`/`interval`; Atlas `continuous` |
| `cron` | five-field `expr`, `tz` | Ledger `cron`, `hourly`, `4hourly`; Atlas `monthly` |
| `on-request` | — | reader actions, a peer's call (the Ledger's fact-check on the Feed) |
| `parked` | — | Atlas `parked`; Ledger `manual` |

### `lanes`

| Field | Meaning |
|---|---|
| `key`, `label`, `what` | the job class, in the app's words |
| `needs.min_ctx` | the smallest context the lane is correct at (`null` = no floor) |
| `needs.speed` | `interactive` (a person is waiting) or `batch` (a block that can wait its turn). The broker's priority classes, when there is one |
| `needs.json` | the lane requires structured output |
| `provider` | the app's provider key: `local` (its Ollama / OpenAI-compatible server), `anthropic`, `openai`, `google`, `deepseek`, `custom` — the Ledger's names |
| `model`, `ctx` | what it runs right now, and at what context (two contexts on one model are two runners to Ollama) |
| `override` | the app lets the Hub pre-populate this lane's provider + model. The app may still override per lane |
| `per_user` | signed-in readers may bring their own API for it (the Feed's reader lane) |

A lane is what the Hub's providers module fills and what the app's own Models
panel edits. The manifest never carries a key, a base URL, or anything the
Hub could not print on a card.

### `usage`

`endpoint` is `null` until the app keeps a per-call log. When it does the
endpoint returns rows of `{ts, app, lane, provider, model, ctx, ms,
tokens_in, tokens_out, ok, error, via}` — exactly what `outset_llm.CallLog`
writes (rule 13; `CallLog.rows(since=…)` serves them, newest first) — and
takes `?since=<iso>`; the Calendar overlays them on the planned blocks.
Saying `null` honestly beats an endpoint that 404s.

## Validating

```python
import outset_manifest as om
problems = om.validate(manifest)     # [] = valid; every departure named
```

Every app that publishes a manifest pins it in a test:
`assert om.validate(build_manifest()) == []`, and `public_view()` on the
anonymous body. The Hub validates what it receives the same way and shows a
registration as *degraded* with the problem list rather than refusing it.

## Vendoring

`outset_manifest.py` is standard-library only and vendors unchanged (the Feed
keeps it at `feed/outset_manifest.py` and its test suite diffs the copy
against this file when the framework is reachable). It joins the parity
check's file list; the CONTRACT mirror rule applies.

## What is not in version 1

* No `secrets` or provider credentials — key custody is the broker's question
  (step 5) and the owner's decision.
* No budgets per app per day — those arrive with the usage log and the Hub's
  calendar, where a number can be seen before it is enforced.
* No "run more often" — by rule 3, never.
