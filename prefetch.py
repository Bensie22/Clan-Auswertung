import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

try:
    from app.services import build_players_enriched, build_warning_candidates, build_promotion_candidates
    from app.routes.analytics import players_leaderboard
except ImportError as e:
    print(f"[ERROR] Import fehlgeschlagen: {e}")
    sys.exit(1)

try:
    data = {
        "leaderboard": players_leaderboard(),
        "warnings":    {"players": build_warning_candidates()},
        "promotions":  {"players": build_promotion_candidates()},
    }
except Exception as e:
    print(f"[ERROR] Datenabruf fehlgeschlagen – prefetch abgebrochen: {e}")
    sys.exit(1)

with open(BASE_DIR / "_prefetch.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("PREFETCH DONE")
