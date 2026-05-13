# Clan-Auswertung HAMBURG

Automatisierte Clash-Royale-Clanverwaltung für Clan **HAMBURG** (`#Y9YQC8UG`).
Site: [clan-hamburg.de](https://clan-hamburg.de) · API: [clan-gpt-api.onrender.com](https://clan-gpt-api.onrender.com)

Zwei Python-Runtimes, ein State:
- **`Master_Auswertung_GitHub.py`** — Cron-Batch (alle 10 Min., GitHub Actions). Holt Spieler- und Kriegsdaten von der Supercell-API, aktualisiert die State-Dateien im Repo-Root und erzeugt im `weekly`-Modus den HTML-Wochenbericht plus Versand-Mail.
- **`api.py`** — schreibgeschützte FastAPI (Render-Deploy). Liest dieselben State-Dateien und proxiert bei Bedarf Live-Calls zur CR-API. Versorgt Frontend, ChatGPT-Aktionen und die Pipeline-Skripte.

Eine kleine **Pipeline** (`prefetch.py` → `full_auto.py` / `smart_mode.py` / `coaching_mode.py` / `commander_mode.py` → `merge_outputs.py`) ruft die API auf und baut die `dashboard_data.json`, die das Frontend (`index.html`) anzeigt.

## Schnelleinstieg

```bash
# 1. Abhängigkeiten
pip install -r requirements.txt

# 2. FastAPI lokal (Port 8001, Live-Reload)
python -m uvicorn api:app --port 8001 --reload

# 3. Statisches Frontend (Port 3000)
python -m http.server 3000

# 4. Cron-Batch testen – benötigt SUPERCELL_API_TOKEN
RUN_MODE=radar python Master_Auswertung_GitHub.py
# Wochenbericht inkl. HTML + (optional) Mail:
RUN_MODE=weekly python Master_Auswertung_GitHub.py

# 5. Pipeline manuell (frisches dashboard_data.json)
python run_pipeline.py
```

Es gibt keine Tests und keinen Linter — Module nach Änderungen mit `python -c "import api"` bzw. dem betroffenen Mode-Skript prüfen.

## Environment

Lokal über `.env`, in Produktion via GitHub-Actions-Secrets bzw. Render-Env-Vars setzen.

| Variable | Wo nötig | Zweck |
|----------|----------|-------|
| `SUPERCELL_API_TOKEN` | GitHub Actions | Direkter Zugriff auf RoyaleAPI-Proxy aus `Master_Auswertung_GitHub.py`. |
| `CR_API_KEY` | Render | Live-Calls aus `app/cr_api.py` (Clan-Profil, Riverrace, Battlelog). |
| `RUN_MODE` | GitHub Actions | `radar` (Default, 10-Min-Cron) oder `weekly` (HTML + Mail). |
| `EMAIL_SENDER` / `EMAIL_PASS` / `EMAIL_RECEIVER` | GitHub Actions | SMTP-Versand des Wochenberichts (nur `weekly`). |
| `IMPRESSUM_*` | GitHub Actions | Werte für Impressum / Datenschutz (Owner, Adresse, Telefon, Mail, Website). |
| `CLAN_TAG` | optional | Überschreibt den Default-Clan in `app/cr_api.py` (`#Y9YQC8UG`). |
| `API_BASE_URL` | optional | Setzt für `api_client.py` eine andere API-Basis (Default Render-Deploy). |

## Wie der Cron läuft

`.github/workflows/main.yml` führt alle 10 Minuten der Reihe nach aus:

1. `Master_Auswertung_GitHub.py` (Datenabruf + State-Mutation, `RUN_MODE=radar`)
2. `prefetch.py` → `_prefetch.json`
3. `full_auto.py`, `smart_mode.py`, `coaching_mode.py`, `commander_mode.py`
4. `merge_outputs.py` → `dashboard_data.json`
5. `git add . && git commit -m "📊 Automatische Clan-Auswertung + Full Auto" && git push`

Dadurch sind die generierten State-Dateien Teil des Repos — das ist das Deploy-Artefakt für GitHub Pages und Render. **Nicht** lokal pushen, ohne Rücksprache: jeder manuelle Push kann den nächsten Cron-Lauf irritieren.

## Konfiguration (Score-Schwellen)

Alle numerischen Grenzwerte stehen in [`config.py`](config.py):

| Konstante | Bedeutung |
|-----------|-----------|
| `STRIKE_THRESHOLD` (50) | Score unter diesem Wert → Verwarnung |
| `KICK_THRESHOLD` (40) | Score unter diesem Wert → Kick-Kandidat |
| `PROMOTION_SCORE_MIN` (85) | Score über diesem Wert + 0 Strikes → Beförderung |
| `SMART_RISIKO_THRESHOLD` (60) / `SMART_STARK_THRESHOLD` (80) | Smart-Mode-Klassifizierung |
| `COACHING_MID_THRESHOLD` (70) | Coaching-Stufe „Konstanz verbessern" |
| `DROPPER_THRESHOLD` (130) / `MIN_PARTICIPATION` (1) | Deck-Qualität / Welpenschutz |
| `BADGE_STARK_*` / `BADGE_STABIL_*` | Badge-Schwellen (Score & Fame) |
| `TIER_SEHR_STARK` (90) / `TIER_SOLIDE` (75) | Tier-Grenzen |
| `CLAN_RELIABLE_GREEN` (85) / `CLAN_RELIABLE_YELLOW` (70) | Clan-Ampel |

FastAPI re-exportiert diese unter `GET /config`, damit Frontend und KI dieselben Werte sehen.

## Architektur

Kurzfassung in [`CLAUDE.md`](CLAUDE.md), Vollreferenz inkl. State-Datei-Schema und Datenfluss in [`docs/code-architecture.md`](docs/code-architecture.md).

```
GitHub Cron ──► Master_Auswertung_GitHub.py ──► State-JSON/CSV im Repo-Root
                                                 │
                                                 ├─► FastAPI (Render) ──► Pipeline ──► dashboard_data.json
                                                 │                                          │
                                                 └─► output/auswertung_*.html (weekly)      ▼
                                                                                       index.html
                                                                                    (GitHub Pages)
```

## Repo-Layout

```
api.py / app/                 FastAPI + Router + Datenzugriff + Services
Master_Auswertung_GitHub.py   Monolithischer Cron-Batch (3700 Zeilen)
config.py                     Single source of truth für Schwellen
prefetch.py / *_mode.py /     Pipeline (API → JSON-Snapshots → dashboard_data.json)
merge_outputs.py / run_pipeline.py
*.json / *.csv (root)         State-Dateien (im Git, vom Cron geschrieben)
index.html / datenschutz.html /    Statisches Frontend + Legal
impressum.html
.github/workflows/main.yml    10-Min-Cron + Commit/Push
docs/                         Architektur-Doku
```

## Mitwirken

- Konventionen, kritische Regeln und Patterns: siehe [`CLAUDE.md`](CLAUDE.md).
- Vor neuen Endpunkten / Mode-Skripten / State-Dateien: [`docs/code-architecture.md`](docs/code-architecture.md) lesen.
- Commit-Stil: Cron committet als `📊 Automatische Clan-Auswertung + Full Auto`. Menschliche Commits sollten sich stilistisch unterscheiden (z. B. `feat: …`, `fix: …`).
- Keine sensiblen Daten committen — `.env`, Secrets, persönliche Spielerdaten gehören nicht ins Repo.

## Lizenz

Keine offene Lizenz vergeben. Code ist projektspezifisch für Clan HAMBURG.
