from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from typing import Annotated
import sqlite3
import uuid
import json
import os

app = FastAPI(title="Clan Action API", version="1.4.0")

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
DB_PATH = BASE_DIR / "action_log.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                id           TEXT PRIMARY KEY,
                timestamp    TEXT NOT NULL,
                action       TEXT NOT NULL,
                player_tag   TEXT NOT NULL,
                player_name  TEXT NOT NULL,
                action_source TEXT DEFAULT 'control_center',
                target_role  TEXT,
                reason       TEXT,
                status       TEXT DEFAULT 'pending',
                updated_at   TEXT
            )
        """)
    _migrate_json()


def _migrate_json():
    """Einmalige Migration: action_log.json → SQLite, falls die Datei noch existiert."""
    legacy = BASE_DIR / "action_log.json"
    if not legacy.exists():
        return
    try:
        entries = json.loads(legacy.read_text(encoding="utf-8"))
        with get_db() as conn:
            for e in entries:
                conn.execute(
                    """INSERT OR IGNORE INTO actions
                       (id, timestamp, action, player_tag, player_name,
                        action_source, target_role, reason, status, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        e.get("id", str(uuid.uuid4())),
                        e.get("timestamp", ""),
                        e.get("action", ""),
                        e.get("player_tag", ""),
                        e.get("player_name", ""),
                        e.get("action_source", "control_center"),
                        e.get("target_role"),
                        e.get("reason"),
                        e.get("status", "pending"),
                        e.get("updated_at"),
                    ),
                )
        legacy.rename(legacy.with_suffix(".json.migrated"))
        print("✅ action_log.json nach SQLite migriert.")
    except Exception as ex:
        print(f"⚠️ Migration fehlgeschlagen: {ex}")


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


init_db()


class ActionRequest(BaseModel):
    action: str
    player_tag: str
    player_name: str
    action_source: str = "control_center"
    target_role: str | None = None
    reason: str | None = None


class ActionStatusUpdate(BaseModel):
    status: str


@app.get("/api/health")
def health():
    return {"success": True, "status": "ok"}


@app.get("/api/actions")
def list_actions():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM actions ORDER BY timestamp DESC"
        ).fetchall()
    actions = [row_to_dict(r) for r in rows]
    return {"success": True, "count": len(actions), "actions": actions}


@app.post("/api/actions/execute")
def execute_action(payload: ActionRequest, x_api_key: Annotated[str, Header()] = ""):
    verify_api_key(x_api_key)
    if payload.action not in {"warn", "kick", "promote"}:
        return {"success": False, "message": f"Unbekannte Aktion: {payload.action}"}

    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "action": payload.action,
        "player_tag": payload.player_tag,
        "player_name": payload.player_name,
        "action_source": payload.action_source,
        "target_role": payload.target_role,
        "reason": payload.reason,
        "status": "pending",
        "updated_at": None,
    }

    with get_db() as conn:
        conn.execute(
            """INSERT INTO actions
               (id, timestamp, action, player_tag, player_name,
                action_source, target_role, reason, status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                entry["id"], entry["timestamp"], entry["action"],
                entry["player_tag"], entry["player_name"], entry["action_source"],
                entry["target_role"], entry["reason"], entry["status"],
            ),
        )

    message_map = {
        "warn":    f"Warnung für {payload.player_name} gespeichert.",
        "kick":    f"Kick-Fall für {payload.player_name} gespeichert.",
        "promote": f"Beförderung für {payload.player_name} gespeichert.",
    }
    return {"success": True, "message": message_map[payload.action], "data": entry}


@app.patch("/api/actions/{action_id}")
def update_action_status(action_id: str, payload: ActionStatusUpdate, x_api_key: Annotated[str, Header()] = ""):
    verify_api_key(x_api_key)
    if payload.status not in {"pending", "done"}:
        raise HTTPException(status_code=400, detail="Ungültiger Status")

    updated_at = datetime.utcnow().isoformat() + "Z"
    with get_db() as conn:
        result = conn.execute(
            "UPDATE actions SET status=?, updated_at=? WHERE id=?",
            (payload.status, updated_at, action_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Aktion nicht gefunden")
        row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()

    return {
        "success": True,
        "message": f"Status auf '{payload.status}' gesetzt.",
        "data": row_to_dict(row),
    }
