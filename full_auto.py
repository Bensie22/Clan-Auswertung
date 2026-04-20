import json
import sys
from config import STRIKE_THRESHOLD, PROMOTION_SCORE_MIN

PRIORITY = {
    "OK": 1,
    "TOP": 2,
    "STRIKE": 4,
    "KEINE_TEILNAHME": 4,
    "STRIKE_ESKALATION": 5,
}

def classify_player(p):
    score = p.get("score", 0)
    strikes = p.get("strikes", 0)

    if score == 0:
        return "KEINE_TEILNAHME", PRIORITY["KEINE_TEILNAHME"]

    if score < STRIKE_THRESHOLD:
        if strikes >= 1:
            return "STRIKE_ESKALATION", PRIORITY["STRIKE_ESKALATION"]
        return "STRIKE", PRIORITY["STRIKE"]

    if score >= PROMOTION_SCORE_MIN:
        return "TOP", PRIORITY["TOP"]

    return "OK", PRIORITY["OK"]

def run():
    try:
        with open("_prefetch.json", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] _prefetch.json nicht lesbar: {e}")
        sys.exit(1)

    warnings   = data.get("warnings", {})
    promotions = data.get("promotions", {})
    events = []

    for p in warnings.get("players", []):
        scenario, priority = classify_player(p)
        events.append({
            "name": p["name"],
            "scenario": scenario,
            "priority": priority
        })

    for p in promotions.get("players", []):
        events.append({
            "name": p["name"],
            "scenario": "TOP",
            "priority": PRIORITY["TOP"]
        })

    events = sorted(events, key=lambda x: x["priority"], reverse=True)

    with open("full_auto_output.json", "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)

    print("FULL AUTO DONE")

if __name__ == "__main__":
    run()
