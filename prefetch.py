import json
import sys
from pathlib import Path
from api_client import get

BASE_DIR = Path(__file__).parent.resolve()

try:
    data = {
        "leaderboard": get("/players/leaderboard"),
        "warnings":    get("/warnings"),
        "promotions":  get("/promotions"),
    }
except RuntimeError as e:
    print(f"[ERROR] API-Abruf fehlgeschlagen – prefetch abgebrochen: {e}")
    sys.exit(1)

with open(BASE_DIR / "_prefetch.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("PREFETCH DONE")
