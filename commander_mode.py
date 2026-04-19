import json
import sys
from config import KICK_THRESHOLD, PROMOTION_SCORE_MIN


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
        "reason": f"Score unter {KICK_THRESHOLD}",
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
        "reason": f"Score über {PROMOTION_SCORE_MIN}",
        "recommended_action": "promote_review"
    }


def is_promotable(player: dict) -> bool:
    role = str(player.get("role", "")).strip().lower()
    score = float(player.get("score", 0) or 0)
    strikes = int(player.get("strikes", 0) or 0)

    return score > PROMOTION_SCORE_MIN and strikes == 0 and role in {"member", "mitglied", ""}


def run():
    try:
        with open("_prefetch.json", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] _prefetch.json nicht lesbar: {e}")
        sys.exit(1)

    players = data.get("leaderboard", {}).get("players", [])

    decisions = {
        "generated_from": "_prefetch.json",
        "remove": [],
        "core": []
    }

    for player in players:
        score = float(player.get("score", 0) or 0)

        if score < KICK_THRESHOLD:
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
