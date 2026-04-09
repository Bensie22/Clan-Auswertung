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

def run():
    leaderboard = get("/players/leaderboard")

    output = []

    for p in leaderboard.get("players", []):
        score = p["score"]

        if score < 50:
            tip = "Mehr Teilnahme notwendig"
        elif score < 70:
            tip = "Konstanz verbessern"
        else:
            tip = "Weiter so"

        output.append({
            "name": p["name"],
            "score": score,
            "tip": tip
        })

    with open("coaching_output.json", "w") as f:
        json.dump(output, f, indent=2)

    print("COACHING DONE")

if __name__ == "__main__":
    run()