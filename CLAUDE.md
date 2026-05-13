# CLAUDE.md

Concise interactions + commit messages. German UI/comments are intentional — keep them German.

## Project Overview

Clash Royale Clan-Management for clan **HAMBURG** (`#Y9YQC8UG`). Two cooperating Python runtimes:

- **`Master_Auswertung_GitHub.py`** — 3700-line batch script. Pulls Supercell data via RoyaleAPI proxy, mutates state JSON/CSVs at repo root, renders HTML report + email. Cron every 10 min in GitHub Actions.
- **`api.py`** (FastAPI, deployed at `clan-gpt-api.onrender.com`) — read-only JSON API over the same state files; serves static `index.html` / legal pages.

Pipeline scripts (`prefetch.py` → `full_auto.py` / `smart_mode.py` / `coaching_mode.py` / `commander_mode.py` → `merge_outputs.py`) call the deployed API and rebuild `dashboard_data.json` consumed by the static frontend.

## Layout

```
api.py                    FastAPI factory, mounts routers, /config, static pages
app/
  cr_api.py               Live Supercell proxy client (uses CR_API_KEY)
  data.py                 Central state-file loader (JSON/CSV at repo root)
  services.py             Score → badge / focus / trend / promotion logic
  utils.py                normalize_tag, normalize_name, parse helpers
  routes/                 clan, player, war, analytics, coaching routers
Master_Auswertung_GitHub.py   Cron batch: fetch + mutate state + render report
config.py                 Single source of truth for thresholds
prefetch.py + *_mode.py + merge_outputs.py   Pipeline scripts → dashboard_data.json
run_pipeline.py           Local orchestrator for the pipeline
docs/                     Deeper architecture reference
```

State files (`member_memory.json`, `donations_memory.json`, `strikes.json`, `records.json`, `player_stats.json`, `top_decks.json`, `player_war_decks.json`, `war_radar_cache.json`, `score_history.csv`, `kicked_players.json`, `urlaub.txt`, `website_opt_out.json`) live at repo root and are committed by the cron.

Dependency direction: routes → `app/services.py` → `app/data.py` / `app/cr_api.py` → state files / Supercell. Don't read state paths directly from route handlers; go through `app/data.py`.

## Commands

```bash
pip install -r requirements.txt
python -m uvicorn api:app --port 8001 --reload         # FastAPI
python -m http.server 3000                             # static frontend
python Master_Auswertung_GitHub.py                     # batch (needs SUPERCELL_API_TOKEN; RUN_MODE=radar|weekly)
python run_pipeline.py                                 # rebuild dashboard_data.json
```

No tests, no linter. After Python edits, smoke via `python -c "import api"` for the FastAPI side or run the affected mode script standalone.

## Critical Rules

1. **`config.py` is the single threshold source.** Never hardcode `STRIKE_THRESHOLD` / `KICK_THRESHOLD` / `PROMOTION_SCORE_MIN` / badge / tier values in routes, mode scripts, or `Master_Auswertung_GitHub.py`. Import from `config`.
2. **Two API tokens, two callers** — `SUPERCELL_API_TOKEN` (used by `Master_Auswertung_GitHub.py` directly) and `CR_API_KEY` (used by `app/cr_api.py` on Render). Don't unify without checking both deploy targets.
3. **Keep German strings German.** User-facing messages, variable names like `rueckkehrer`, log prefixes (✅ ⚠️ ❌ 🔥) are intentional.
4. **State files = deploy artifact.** Large generated files (`top_decks.json`, `player_war_decks.json` — both ~4 MB) live in git on purpose. Never `.gitignore` them.
5. **`RUN_MODE` switch** — `Master_Auswertung_GitHub.py` reads `RUN_MODE` env (default `radar`); `weekly` triggers full HTML report + email, `radar` skips both. Cron sets `radar`.
6. **Timezone for week-boundary logic is `Europe/Berlin`** (via `zoneinfo`). Don't switch to naive `datetime.now()`.
7. **Don't collide with cron commit message** — GitHub Action commits as `📊 Automatische Clan-Auswertung + Full Auto`. Use a different message style for human commits.
8. **Player tag normalization** — always go through `app/utils.py::normalize_tag` (URL-encoded `%23` ↔ `#` is a frequent footgun).
9. **Never push without explicit user review.** No PRs without approval.

## Patterns

### State-file access through `app/data.py`

```python
from app.data import load_strikes_raw, load_player_stats
# not: json.load(open("strikes.json"))
```

`app/data.py` centralizes paths (`STRIKES_PATH`, `RECORDS_PATH`, …) and provides graceful fallbacks (`load_json(path, default)`).

### Mode-script contract

Each pipeline mode script:
1. reads `_prefetch.json` (written by `prefetch.py`),
2. classifies / transforms,
3. writes `<name>_output.json`.

Adding a mode = new script writing `<name>_output.json` + register in `merge_outputs.py` + `run_pipeline.py::STEPS` + workflow YAML steps.

### Threshold consumption

```python
from config import STRIKE_THRESHOLD, PROMOTION_SCORE_MIN
```

The FastAPI `/config` endpoint re-exports these so the frontend can't drift.

## Quick Reference

| Need | Path |
|------|------|
| New FastAPI endpoint | `app/routes/<topic>.py` (existing: clan, player, war, analytics, coaching) |
| Cross-route business logic | `app/services.py` |
| State-file read helper | `app/data.py` |
| Live Supercell call | `app/cr_api.py::cr_api_get` |
| Threshold / score boundary | `config.py` (only) |
| New pipeline mode | `<name>_mode.py` + entry in `merge_outputs.py` + `run_pipeline.py::STEPS` + workflow YAML |
| Cron schedule / env wiring | `.github/workflows/main.yml` |
| Static page / dashboard markup | `index.html`, `datenschutz.html`, `impressum.html` |
| Legal page generation | `Master_Auswertung_GitHub.py::build_legal_pages` / `write_static_legal_pages` |

## External Systems

| System | Used for | Touched in |
|--------|----------|------------|
| **Supercell CR API** (via `proxy.royaleapi.dev`) | Clan, members, river race, war log, battle log, player decks | `Master_Auswertung_GitHub.py` (token `SUPERCELL_API_TOKEN`), `app/cr_api.py` (key `CR_API_KEY`) |
| **GitHub Actions** | 10-minute cron + commit/push of state files | `.github/workflows/main.yml` |
| **Render** | FastAPI deploy (`clan-gpt-api.onrender.com`) | `api.py` OpenAPI server URL pinned here |
| **SMTP (`EMAIL_*` secrets)** | Weekly report email | `Master_Auswertung_GitHub.py::sende_bericht_per_mail` (only `RUN_MODE=weekly`) |
| **GitHub Pages (`CNAME` → `clan-hamburg.de`)** | Static frontend hosting | `CNAME`, `index.html` |

## Docs Index

| Path | Purpose |
|------|---------|
| [`docs/code-architecture.md`](docs/code-architecture.md) | Full file map, data flow, batch vs. API split, state-file schemas, where-to-put guide. **Read before adding features.** |

When the deeper file changes (new package, new state file, new system integration), update `docs/code-architecture.md` and bump the relevant CLAUDE.md section.
