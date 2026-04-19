import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

def load(filename):
    path = BASE_DIR / filename
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

data = {
    "full_auto": load("full_auto_output.json"),
    "smart":     load("smart_output.json"),
    "coaching":  load("coaching_output.json"),
    "commander": load("commander_output.json"),
}

with open(BASE_DIR / "dashboard_data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("MERGE DONE")
