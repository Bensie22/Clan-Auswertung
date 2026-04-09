import json
from config import SMART_RISIKO_THRESHOLD, SMART_STARK_THRESHOLD

def run():
    with open("_prefetch.json", encoding="utf-8") as f:
        data = json.load(f)

    leaderboard = data.get("leaderboard", {})
    results = []

    for p in leaderboard.get("players", []):
        score = p["score"]

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
