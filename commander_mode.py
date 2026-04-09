import json
import requests

BASE_URL = "https://clan-gpt-api.onrender.com"


def get(endpoint: str) -> dict:
    response = requests.get(BASE_URL + endpoint, timeout=20)
    response.raise_for_status()
    return response.json()


def build_remove_entry(player: dict) -> dict:
    return {
        "name": player.get("name"),
        "player_tag": player.get("tag"),
        "role": player.get("role"),
        "score": player.get("score", 0),
        "strikes": player.get("strikes", 0),
        "donations": player.get("donations", 0),
        "participation_count": player.get("participation_count", 0),
        "trend": player.get("trend", ""),
        "reason": "Score unter 40",
        "recommended_action": "kick_review"
    }


def build_core_entry(player: dict) -> dict:
    return {
        "name": player.get("name"),
        "player_tag": player.get("tag"),
        "role": player.get("role"),
        "score": player.get("score", 0),
        "strikes": player.get("strikes", 0),
        "donations": player.get("donations", 0),
        "participation_count": player.get("participation_count", 0),
        "trend": player.get("trend", ""),
        "reason": "Score über 85",
        "recommended_action": "promote_review"
    }


def is_promotable(player: dict) -> bool:
    role = str(player.get("role", "")).strip().lower()
    score = float(player.get("score", 0) or 0)
    strikes = int(player.get("strikes", 0) or 0)

    return score > 85 and strikes == 0 and role in {"member", "mitglied", ""}


def run():
    leaderboard = get("/players/leaderboard")
    players = leaderboard.get("players", [])

    decisions = {
        "generated_from": "/players/leaderboard",
        "remove": [],
        "core": []
    }

    for player in players:
        score = float(player.get("score", 0) or 0)

        if score < 40:
            decisions["remove"].append(build_remove_entry(player))
        elif is_promotable(player):
            decisions["core"].append(build_core_entry(player))

    decisions["remove"].sort(key=lambda p: (p["score"], -p["strikes"]))
    decisions["core"].sort(key=lambda p: (-p["score"], p["strikes"], -p["donations"]))

    with open("commander_output.json", "w", encoding="utf-8") as f:
        json.dump(decisions, f, indent=2, ensure_ascii=False)

    print("COMMANDER DONE")


if __name__ == "__main__":
    run()