import requests
import json

BASE_URL = "https://clan-gpt-api.onrender.com"

def get(endpoint):
    return requests.get(BASE_URL + endpoint).json()

def run():
    leaderboard = get("/players/leaderboard")

    decisions = {
        "remove": [],
        "core": []
    }

    for p in leaderboard.get("players", []):
        score = p["score"]

        if score < 40:
            decisions["remove"].append(p["name"])
        elif score > 85:
            decisions["core"].append(p["name"])

    with open("commander_output.json", "w") as f:
        json.dump(decisions, f, indent=2)

    print("COMMANDER DONE")

if __name__ == "__main__":
    run()