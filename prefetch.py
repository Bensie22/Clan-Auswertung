import json
from api_client import get

data = {
    "leaderboard": get("/players/leaderboard"),
    "warnings":    get("/warnings"),
    "promotions":  get("/promotions"),
}

with open("_prefetch.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("PREFETCH DONE")
