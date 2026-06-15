"""Lädt Kriegsverlauf aller Spieler einmalig von Render und speichert lokal als warlog_cache.json."""
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).parent
API = os.environ.get("API_BASE_URL", "https://clan-gpt-api.onrender.com")
API_KEY = os.environ.get("CLAN_API_KEY", "")

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

out = BASE / "warlog_cache.json"
out.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nGespeichert: {out}")
print(f"Erfolgreich: {len(players) - errors} | Fehler: {errors}")
