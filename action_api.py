from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from typing import Annotated
import json
import uuid
import os

app = FastAPI(title="Clan Action API", version="1.3.0")

# CORS freigeben für dein lokales Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.clan-hamburg.de",
        "https://clan-hamburg.de",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

# API-Key-Authentifizierung (setze ACTION_API_KEY als Umgebungsvariable)
_API_KEY = os.environ.get("ACTION_API_KEY", "")


def verify_api_key(x_api_key: Annotated[str, Header()] = ""):
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Ungültiger API-Key")

BASE_DIR = Path(__file__).parent.resolve()
ACTION_LOG_PATH = BASE_DIR / "action_log.json"


class ActionRequest(BaseModel):
    action: str
    player_tag: str
    player_name: str
    action_source: str = "control_center"
    target_role: str | None = None
    reason: str | None = None


class ActionStatusUpdate(BaseModel):
    status: str


def load_logs() -> list:
    if not ACTION_LOG_PATH.exists():
        return []
    try:
        return json.loads(ACTION_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_logs(logs: list):
    ACTION_LOG_PATH.write_text(
        json.dumps(logs, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


@app.get("/api/health")
def health():
    return {"success": True, "status": "ok"}


@app.get("/api/actions")
def list_actions():
    logs = load_logs()
    logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {
        "success": True,
        "count": len(logs),
        "actions": logs
    }


@app.post("/api/actions/execute")
def execute_action(payload: ActionRequest, x_api_key: Annotated[str, Header()] = ""):
    verify_api_key(x_api_key)
    if payload.action not in {"warn", "kick", "promote"}:
        return {
            "success": False,
            "message": f"Unbekannte Aktion: {payload.action}"
        }

    logs = load_logs()

    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "action": payload.action,
        "player_tag": payload.player_tag,
        "player_name": payload.player_name,
        "action_source": payload.action_source,
        "target_role": payload.target_role,
        "reason": payload.reason,
        "status": "pending"
    }

    logs.append(entry)
    save_logs(logs)

    message_map = {
        "warn": f"Warnung für {payload.player_name} gespeichert.",
        "kick": f"Kick-Fall für {payload.player_name} gespeichert.",
        "promote": f"Beförderung für {payload.player_name} gespeichert."
    }

    return {
        "success": True,
        "message": message_map[payload.action],
        "data": entry
    }


@app.patch("/api/actions/{action_id}")
def update_action_status(action_id: str, payload: ActionStatusUpdate, x_api_key: Annotated[str, Header()] = ""):
    verify_api_key(x_api_key)
    if payload.status not in {"pending", "done"}:
        raise HTTPException(status_code=400, detail="Ungültiger Status")

    logs = load_logs()
    for entry in logs:
        if entry.get("id") == action_id:
            entry["status"] = payload.status
            entry["updated_at"] = datetime.utcnow().isoformat() + "Z"
            save_logs(logs)
            return {
                "success": True,
                "message": f"Status auf '{payload.status}' gesetzt.",
                "data": entry
            }

    raise HTTPException(status_code=404, detail="Aktion nicht gefunden")