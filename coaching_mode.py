import json
from config import COACHING_WARN_THRESHOLD, COACHING_MID_THRESHOLD

def run():
    with open("_prefetch.json", encoding="utf-8") as f:
        data = json.load(f)

    leaderboard = data.get("leaderboard", {})
    output = []

    for p in leaderboard.get("players", []):
        score = p["score"]

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
