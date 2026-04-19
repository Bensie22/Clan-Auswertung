import json
import sys
from config import SMART_RISIKO_THRESHOLD, SMART_STARK_THRESHOLD

def run():
    try:
        with open("_prefetch.json", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] _prefetch.json nicht lesbar: {e}")
        sys.exit(1)

    leaderboard = data.get("leaderboard", {})
    results = []

    for p in leaderboard.get("players", []):
        score = p.get("score", 0)

        if score < SMART_RISIKO_THRESHOLD:
            status = "RISIKO"
        elif score > SMART_STARK_THRESHOLD:
            status = "STARK"
        else:
            status = "OK"

        results.append({
            "name": p["name"],
            "score": score,
            "status": status
        })

    with open("smart_output.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("SMART MODE DONE")

if __name__ == "__main__":
    run()
