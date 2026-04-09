import json
from config import STRIKE_THRESHOLD, PROMOTION_SCORE_MIN

def classify_player(p):
    score = p["score"]
    strikes = p["strikes"]

    if score == 0:
        return "KEINE_TEILNAHME", 4

    if score < STRIKE_THRESHOLD:
        if strikes >= 2:
            return "STRIKE_ESKALATION", 5
        return "STRIKE", 4

    if score >= PROMOTION_SCORE_MIN:
        return "TOP", 2

    return "OK", 1

def run():
    with open("_prefetch.json", encoding="utf-8") as f:
        data = json.load(f)

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
            "priority": 2
        })

    events = sorted(events, key=lambda x: x["priority"], reverse=True)

    with open("full_auto_output.json", "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)

    print("FULL AUTO DONE")

if __name__ == "__main__":
    run()
