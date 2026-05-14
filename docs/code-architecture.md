# Code Architecture

Reference map for Clan-Auswertung. Read before adding endpoints, mode scripts, state files, or external-system integrations.

## Repo layout

```
Clan-Auswertung/
├── api.py                          FastAPI factory, OpenAPI override, /config, static pages
├── Master_Auswertung_GitHub.py     Monolithic cron batch: fetch + state mutation + HTML report + email
├── config.py                       Single threshold source — STRIKE/KICK/PROMOTION/badge/tier/ampel
├── app/
│   ├── cr_api.py                   Live Supercell client via RoyaleAPI proxy (CR_API_KEY)
│   ├── data.py                     Central JSON/CSV loader for repo-root state files
│   ├── services.py                 Score → badge / focus / trend / promotion-status logic
│   ├── utils.py                    normalize_tag, normalize_name, parse_int/float
│   └── routes/                     FastAPI routers
│       ├── clan.py                 /summary, /players, /warnings, /promotions, /strikes, /records, /kicked, /clan/live
│       ├── player.py               /player/{tag}, /player/{tag}/{history,warlog,decks,focus,streak,promotion-status,stats,battlelog,live}
│       ├── war.py                  /warlog, /warlog/current, /war/{mahnwache,radar,prognose,status,history,live-participants}
│       ├── analytics.py            /analytics/{teamplay,clan-quality}, /players/{leaderboard,trends,streaks,comebacks,activity,search,inaktiv,donations,meta}, /compare
│       └── coaching.py             /coaching/{tips,messages}, /promotions/progress, /player/{tag}/coaching
├── prefetch.py                     Calls deployed API → _prefetch.json (leaderboard, warnings, promotions)
├── full_auto.py                    _prefetch.json → full_auto_output.json (event prioritization)
├── smart_mode.py                   _prefetch.json → smart_output.json (RISIKO/OK/STARK)
├── coaching_mode.py                _prefetch.json → coaching_output.json (tip per player)
├── commander_mode.py               _prefetch.json → commander_output.json (kick + promote review lists)
├── merge_outputs.py                *_output.json → dashboard_data.json
├── run_pipeline.py                 Local orchestrator (prefetch → modes → merge)
├── api_client.py                   Shared HTTP GET wrapper (used by pipeline scripts)
├── index.html / datenschutz.html / impressum.html   Static frontend + legal
├── .github/workflows/main.yml      Cron every 10 min: master → prefetch → modes → merge → commit + push
└── docs/                           you are here
```

## Two cooperating runtimes

```
                      ┌─────────────────────────────────────┐
                      │  GitHub Actions (cron, every 10m)   │
                      │   RUN_MODE=radar                    │
                      └────────────────┬────────────────────┘
                                       │
                  ┌────────────────────▼────────────────────────────────┐
                  │  Master_Auswertung_GitHub.py                        │
                  │  - fetch_and_build_player_csv (Supercell)           │
                  │  - update_top_decks, fetch_player_profiles          │
                  │  - mutate member_memory / donations / strikes /     │
                  │    records / score_history / top_decks / …          │
                  │  - if RUN_MODE=weekly: render HTML + send email     │
                  └────────────────┬─────────────────┬──────────────────┘
                                   │ writes          │ writes
                       ┌───────────▼─────────┐  ┌────▼──────────────────┐
                       │ Repo-root state     │  │ output/auswertung_*   │
                       │  *.json / *.csv     │  │ + email (weekly only) │
                       └───────────┬─────────┘  └───────────────────────┘
                                   │ reads
                  ┌────────────────▼──────────────────────────────┐
                  │  FastAPI (Render: clan-gpt-api.onrender.com)  │
                  │  api.py → routers in app/routes/              │
                  │   • Reads via app/data.py                     │
                  │   • Live Supercell via app/cr_api.py          │
                  │   • Re-exports config.py at /config           │
                  └────────────────┬──────────────────────────────┘
                                   │ called by
                  ┌────────────────▼───────────────────────────┐
                  │  Pipeline (cron continues)                 │
                  │  prefetch.py → _prefetch.json              │
                  │  full_auto / smart / coaching / commander  │
                  │   → *_output.json                          │
                  │  merge_outputs.py → dashboard_data.json    │
                  └────────────────┬───────────────────────────┘
                                   │ commit + push
                  ┌────────────────▼──────────────────┐
                  │  Static frontend (GitHub Pages)   │
                  │  index.html reads dashboard_data  │
                  └───────────────────────────────────┘
```

## Layer responsibilities

| Layer | Owns | Does NOT |
|-------|------|----------|
| **`config.py`** | All numeric thresholds (strike / kick / promotion / badges / tiers / ampel / smart / coaching). | Contain logic. |
| **`app/utils.py`** | Pure helpers: tag/name normalization, parse_int / parse_float. | Touch I/O. |
| **`app/data.py`** | Centralized JSON/CSV loaders + path constants. Safe fallbacks via `load_json(path, default)`. | Hold business rules. |
| **`app/cr_api.py`** | RoyaleAPI proxy client. `cr_api_get` raises `HTTPException` with proper status codes. | Persist state. |
| **`app/services.py`** | Composes data loaders into enriched player views; encodes score → badge / focus / trend / promotion-status / streak rules. | Talk to Supercell / HTTP. |
| **`app/routes/*`** | URL → service call → JSON shape. Thin. | Read state files directly; encode business rules. |
| **`Master_Auswertung_GitHub.py`** | Cron-driven Supercell fetch + every state-file mutation + HTML report rendering + email. | Be imported elsewhere. |
| **Pipeline scripts** | Pure transforms over `_prefetch.json`, each producing one `*_output.json`. | Reach the DB / Supercell directly (always call the deployed API). |

## State files (repo-root JSON/CSV)

| File | Written by | Read by | Holds |
|------|------------|---------|-------|
| `member_memory.json` | Master | Master, `/players` paths | `current_players`, `ever_seen_players`, `pending_events` (24h TTL join detection) |
| `donations_memory.json` | Master | `app/data.py::load_donations_map` | Spenden-Verlauf pro Spieler |
| `strikes.json` | Master | `/strikes`, services | Verwarnungen + Demoted/Kicked this week |
| `records.json` | Master | `/records` | Clan-Bestmarken |
| `kicked_players.json` | Master | `/kicked`, Master (returning detection) | Liste gekickter Spieler |
| `score_history.csv` | Master | services (trend, streak) | Wöchentlicher Score pro Spieler |
| `player_stats.json` | Master | `/player/{tag}/stats`, services | Aggregierte Statistik je Spielertag |
| `top_decks.json` (~4 MB) | Master | `/players/meta`, frontend | Top-Decks der Klanmitglieder |
| `player_war_decks.json` (~4 MB) | Master | `/player/{tag}/decks` | War-Deck-Historie je Spieler |
| `war_radar_cache.json` | Master | Master (Delta zwischen Cron-Läufen) | `periodPoints` Snapshot je Clan |
| `urlaub.txt` | Manuell | Master | Urlaubsmeldungen (Welpenschutz) |
| `website_opt_out.json` | Manuell | Master | Spieler/Tags die im Web ausgeblendet werden |
| `_prefetch.json` | `prefetch.py` | mode scripts | leaderboard + warnings + promotions Snapshot |
| `full_auto_output.json` / `smart_output.json` / `coaching_output.json` / `commander_output.json` | mode scripts | `merge_outputs.py` | Mode-Result |
| `dashboard_data.json` | `merge_outputs.py` | `index.html` | Vereinigtes Dashboard-Payload |
| `action_log.db` | Master | Master | SQLite Aktionslog |

## External systems

| System | Used for | Touched in | Auth |
|--------|----------|------------|------|
| **RoyaleAPI proxy** (`proxy.royaleapi.dev/v1`) | Supercell CR API (clan, members, riverrace, warlog, battlelog, decks) | `Master_Auswertung_GitHub.py`, `app/cr_api.py` | `SUPERCELL_API_TOKEN` (batch), `CR_API_KEY` (API) |
| **GitHub Actions** | 10-min cron, commit/push of generated state | `.github/workflows/main.yml` | Repo secrets (`SUPERCELL_API_TOKEN`, `EMAIL_*`, `IMPRESSUM_*`) |
| **Render** | FastAPI deploy | `api.py` (OpenAPI server URL pinned to `clan-gpt-api.onrender.com`) | `CR_API_KEY` env in Render |
| **SMTP** | Weekly report email | `Master_Auswertung_GitHub.py::sende_bericht_per_mail` (only `RUN_MODE=weekly`) | `EMAIL_PASS` / `EMAIL_SENDER` / `EMAIL_RECEIVER` |
| **GitHub Pages** | Static hosting at `clan-hamburg.de` | `CNAME`, `index.html`, `datenschutz.html`, `impressum.html` | n/a |

Two API token names is intentional, not a bug — batch and FastAPI are wired up by different deploys with different secret stores.

## RUN_MODE

`Master_Auswertung_GitHub.py::main()` reads `RUN_MODE` env (default `radar`):

| Mode | Does | Skips |
|------|------|-------|
| `radar` (cron default) | Fetch + state mutation + `war_radar_cache` delta | HTML rendering, weekly history append, email |
| `weekly` | Everything radar does + weekly history append + HTML report + email | — |

Switch via workflow YAML `env.RUN_MODE` or one-off `workflow_dispatch`.

## Patterns

### Injectable nothing — direct imports, single instance

This codebase isn't DI-style. `app/data.py` and `app/services.py` expose plain functions that read state files at call time. Routes call them directly:

```python
from app.services import build_players_enriched, build_warning_candidates
from app.data import load_records, load_strikes_raw
```

When adding a new state file, add the path constant + loader in `app/data.py`, then a `build_*` aggregate in `app/services.py` if it needs cross-file joins.

### Service layer joins state files

`build_players_enriched` in `app/services.py` joins `member_memory.json`, `player_stats.json`, `score_history.csv`, `donations_memory.json`, `strikes.json` into one enriched dict. New cross-file features should extend this rather than re-loading files per route.

### Threshold re-export at `/config`

`api.py::APP_CONFIG` mirrors selected names from `config.py` and is served at `GET /config` so the frontend / KI configuration reads them at runtime and cannot drift.

### Mode-script contract

```python
# <name>_mode.py skeleton
import json, sys
from config import <thresholds>

with open("_prefetch.json", encoding="utf-8") as f:
    data = json.load(f)

result = transform(data)

with open("<name>_output.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print("<NAME> DONE")
```

Register the new script in three places:
- `merge_outputs.py` (`data["<name>"] = load("<name>_output.json")`)
- `run_pipeline.py` (`STEPS` list)
- `.github/workflows/main.yml` (add step before `Outputs zusammenführen`)

### Clan tag handling

`Master_Auswertung_GitHub.py` uses URL-encoded form: `CLAN_TAG = "%23Y9YQC8UG"`.
`app/cr_api.py` builds both raw and encoded forms from the `CLAN_TAG` env (default `#Y9YQC8UG`).
Player tags are normalized via `app/utils.py::normalize_tag` — always go through it; `#` ↔ `%23` ↔ uppercase mismatch is the most common bug source.

### Timezone

Week-boundary logic uses `zoneinfo.ZoneInfo("Europe/Berlin")`. Don't substitute naive `datetime.now()` — the GitHub runner is UTC and Sunday vs. Saturday rollover happens at 22:00 UTC in winter.

## Where to put new code

| Need | Goes in |
|------|---------|
| New score / threshold knob | `config.py` (and surface via `/config` in `api.py` if frontend needs it) |
| Pure helper (parse, normalize, format) | `app/utils.py` |
| New repo-root state file | path const + loader in `app/data.py`; writer stays in `Master_Auswertung_GitHub.py` |
| Cross-state aggregation / score-derived flag | `app/services.py` |
| New REST endpoint | the right router in `app/routes/`; new topic ⇒ new router file + `app.include_router` in `api.py` |
| Live Supercell call from API | wrap in `app/cr_api.py`; never `requests.get` in a route |
| New cron-driven mutation | function in `Master_Auswertung_GitHub.py` + call from `main()` |
| New "mode" view | `<name>_mode.py` + entries in `merge_outputs.py`, `run_pipeline.py`, workflow YAML |
| New cron job (different schedule) | additional job in `.github/workflows/main.yml` |
| Frontend layout / chart | `index.html` (single-file SPA-ish frontend) |
| Legal text | env-driven content in `Master_Auswertung_GitHub.py::build_legal_pages` |

## Useful conventions

- **Print prefixes**: ✅ success, ⚠️ soft warning, ❌ fatal, 🔥 highlight, 💡 info. The GitHub Action surfaces these literally.
- **Commit messages**: GitHub Action commits as `📊 Automatische Clan-Auswertung + Full Auto`. Human commits should diverge stylistically.
- **German naming**: variable names like `rueckkehrer`, `urlaub`, `welpenschutz` carry domain meaning — don't anglicize.
- **No tests, no linter**: validate by importing the module (`python -c "import api"`) or running the affected mode script standalone before commit.
- **Welpenschutz**: first clan war is grace-period (`MIN_PARTICIPATION`) — preserved by `participation_count` checks in `app/services.py::get_focus_badge` and Master.
