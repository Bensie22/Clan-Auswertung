import json

def load(file):
    try:
        with open(file) as f:
            return json.load(f)
    except:
        return {}

data = {
    "full_auto": load("full_auto_output.json"),
    "smart": load("smart_output.json"),
    "coaching": load("coaching_output.json"),
    "commander": load("commander_output.json")
}

with open("dashboard_data.json", "w") as f:
    json.dump(data, f, indent=2)

print("MERGE DONE")