from fastapi import FastAPI
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
import json

app = FastAPI(title="Clan Action API", version="1.0.0")

BASE_DIR = Path(__file__).parent.resolve()
ACTION_LOG_PATH = BASE_DIR / "action_log.json"


class ActionRequest(BaseModel):
    action: str
    player_tag: str
    player_name: str
    action_source: str = "control_center"
    target_role: str | None = None


def append_action_log(entry: dict):
    logs = []
    if ACTION_LOG_PATH.exists():
        try:
            logs = json.loads(ACTION_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            logs = []

    logs.append(entry)
    ACTION_LOG_PATH.write_text(
        json.dumps(logs, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


@app.get("/api/health")
def health():
    return {"success": True, "status": "ok"}


@app.post("/api/actions/execute")
def execute_action(payload: ActionRequest):
    if payload.action not in {"warn", "kick", "promote"}:
        return {
            "success": False,
            "message": f"Unbekannte Aktion: {payload.action}"
        }

    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "action": payload.action,
        "player_tag": payload.player_tag,
        "player_name": payload.player_name,
        "action_source": payload.action_source,
        "target_role": payload.target_role,
        "status": "logged_only"
    }

    append_action_log(log_entry)

    message_map = {
        "warn": f"Warnung für {payload.player_name} wurde protokolliert.",
        "kick": f"Kick-Fall für {payload.player_name} wurde protokolliert.",
        "promote": f"Beförderung für {payload.player_name} wurde protokolliert."
    }

    return {
        "success": True,
        "message": message_map[payload.action],
        "data": log_entry
    }