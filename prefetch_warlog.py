"""Lädt Kriegsverlauf aller Spieler von Render und speichert lokal als warlog_cache.json.

Wird nur einmal pro Woche tatsächlich gegen Render abgefragt: ab Montag 12:00 Uhr
(Europe/Berlin), wenn der Clankrieg vorbei ist. Der Zeitpunkt des letzten Refreshs
wird im Cache-Inhalt selbst gespeichert (Schlüssel "_meta"), nicht im Datei-mtime --
GitHub Actions checkt das Repo bei jedem Lauf frisch aus, wodurch ein mtime-basiertes
Gate bei jedem Lauf zurückgesetzt würde. Der Cache muss daher committet werden
(nicht in .gitignore), damit "_meta.last_refresh" über Workflow-Läufe hinweg
erhalten bleibt. Ein verpasstes Fenster wird beim nächsten Lauf automatisch
nachgeholt, löst danach aber keine weiteren Abfragen mehr aus, bis zum nächsten
Montag.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).parent
API = os.environ.get("API_BASE_URL", "https://clan-gpt-api.onrender.com")
API_KEY = os.environ.get("CLAN_API_KEY", "")
BERLIN = ZoneInfo("Europe/Berlin")
cache_path = BASE / "warlog_cache.json"
META_KEY = "_meta"


def last_monday_noon(now: datetime) -> datetime:
    days_since_monday = now.weekday()  # Montag = 0
    candidate = (now - timedelta(days=days_since_monday)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    if now < candidate:
        candidate -= timedelta(days=7)
    return candidate


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def last_refresh(cache: dict) -> datetime | None:
    raw = cache.get(META_KEY, {}).get("last_refresh")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def cache_needs_refresh(cache: dict, now: datetime) -> bool:
    refreshed_at = last_refresh(cache)
    return refreshed_at is None or refreshed_at < last_monday_noon(now)


existing_cache = load_cache(cache_path)

if not cache_needs_refresh(existing_cache, datetime.now(BERLIN)):
    print(
        "Warlog-Cache ist aktuell (seit letztem Montag 12:00 Uhr Europe/Berlin) "
        "— kein Render-Abruf nötig."
    )
    sys.exit(0)

players = json.loads((BASE / "player_stats.json").read_text(encoding="utf-8"))
headers = {"X-Api-Key": API_KEY} if API_KEY else {}

cache = {}
errors = 0

print(f"Lade Kriegsverlauf für {len(players)} Spieler von {API} ...")

for i, p in enumerate(players):
    tag = p["tag"]
    enc = tag.replace("#", "%23")
    url = f"{API}/player/{enc}/warlog"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        cache[tag] = data.get("wars", [])
        print(f"  [{i+1}/{len(players)}] {p['name']}: {len(cache[tag])} Kriege")
    except Exception as e:
        print(f"  [{i+1}/{len(players)}] {p['name']}: FEHLER – {e}")
        cache[tag] = []
        errors += 1
    time.sleep(0.2)

cache[META_KEY] = {"last_refresh": datetime.now(BERLIN).isoformat()}

cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nGespeichert: {cache_path}")
print(f"Erfolgreich: {len(players) - errors} | Fehler: {errors}")
