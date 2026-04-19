import json
import sys
from config import COACHING_WARN_THRESHOLD, COACHING_MID_THRESHOLD

def run():
    try:
        with open("_prefetch.json", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] _prefetch.json nicht lesbar: {e}")
        sys.exit(1)

    leaderboard = data.get("leaderboard", {})
    output = []

    for p in leaderboard.get("players", []):
        score = p.get("score", 0)

        if score < COACHING_WARN_THRESHOLD:
            tip = "Mehr Teilnahme notwendig"
        elif score < COACHING_MID_THRESHOLD:
            tip = "Konstanz verbessern"
        else:
            tip = "Weiter so"

        output.append({
            "name": p["name"],
            "score": score,
            "tip": tip
        })

    with open("coaching_output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("COACHING DONE")

if __name__ == "__main__":
    run()
