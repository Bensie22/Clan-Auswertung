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

    results = []

    for p in leaderboard.get("players", []):
        score = p["score"]

        if score < 60:
            status = "RISIKO"
        elif score > 80:
            status = "STARK"
        else:
            status = "OK"

        results.append({
            "name": p["name"],
            "score": score,
            "status": status
        })

    with open("smart_output.json", "w") as f:
        json.dump(results, f, indent=2)

    print("SMART MODE DONE")

if __name__ == "__main__":
    run()