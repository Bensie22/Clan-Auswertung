import requests
import json

BASE_URL = "https://clan-gpt-api.onrender.com"

def get(endpoint):
    return requests.get(BASE_URL + endpoint).json()

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