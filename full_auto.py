import requests
import json
import sys

BASE_URL = "https://clan-gpt-api.onrender.com"

def get(endpoint: str) -> dict:
    try:
        response = requests.get(BASE_URL + endpoint, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ API-Fehler bei {endpoint}: {e}")
        sys.exit(1)

def classify_player(p):
    score = p["score"]
    strikes = p["strikes"]

    if score == 0:
        return "KEINE_TEILNAHME", 4

    if score < 50:
        if strikes >= 2:
            return "STRIKE_ESKALATION", 5
        return "STRIKE", 4

    if score >= 85:
        return "TOP", 2

    return "OK", 1

def run():
    warnings = get("/warnings")
    promotions = get("/promotions")

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

    with open("full_auto_output.json", "w") as f:
        json.dump(events, f, indent=2)

    print("FULL AUTO DONE")

if __name__ == "__main__":
    run()