from fastapi import FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from pathlib import Path
from typing import Any, Dict, List, Optional
import csv
import json

app = FastAPI(title="Clash Royale Clan Management API", version="2.0.0")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Clash Royale Clan Management API",
        version="2.0.0",
        description="JSON-first API für Clanführung, Warnungen, Beförderungen und Spielerübersichten.",
        routes=app.routes,
    )
    openapi_schema["servers"] = [{"url": "https://clan-gpt-api.onrender.com"}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

BASE_DIR = Path(__file__).parent.resolve()
STRIKES_PATH = BASE_DIR / "strikes.json"
RECORDS_PATH = BASE_DIR / "records.json"
SCORE_HISTORY_PATH = BASE_DIR / "score_history.csv"
MEMBER_MEMORY_PATH = BASE_DIR / "member_memory.json"
KICKED_PLAYERS_PATH = BASE_DIR / "kicked_players.json"
DONATIONS_MEMORY_PATH = BASE_DIR / "donations_memory.json"

STRIKE_THRESHOLD = 50
PROMOTION_SCORE_MIN = 85
PROMOTION_DONATIONS_MIN = 50
NAME_STRIKE_LOOKUP = {"amp", "gang", "bequemo"}


def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def normalize_tag(tag: str) -> str:
    tag = str(tag or "").strip().upper()
    if not tag:
        return ""
    if not tag.startswith("#"):
        tag = f"#{tag}"
    return tag


def normalize_name(name: str) -> str:
    return str(name or "").strip().lower().replace("_", "")


def load_member_memory() -> Dict[str, Any]:
    return load_json(MEMBER_MEMORY_PATH, {"current_players": {}, "pending_events": []})


def load_donations_memory() -> Dict[str, Any]:
    return load_json(DONATIONS_MEMORY_PATH, {"players": {}})


def load_strikes_raw() -> Dict[str, Any]:
    return load_json(STRIKES_PATH, {"players": {}, "demoted_this_week": [], "kicked_this_week": []})


def load_records() -> Dict[str, Any]:
    return load_json(RECORDS_PATH, {})


def load_kicked_players() -> List[Any]:
    data = load_json(KICKED_PLAYERS_PATH, [])
    return data if isinstance(data, list) else []


def load_current_players() -> Dict[str, Dict[str, Any]]:
    raw = load_member_memory()
    players = raw.get("current_players", {}) if isinstance(raw, dict) else {}
    result: Dict[str, Dict[str, Any]] = {}
    for raw_tag, info in players.items():
        tag = normalize_tag(raw_tag)
        if not tag:
            continue
        info = info if isinstance(info, dict) else {}
        result[tag] = {
            "tag": tag,
            "name": info.get("name", "Unbekannt"),
            "role": info.get("role", "member"),
            "last_seen": info.get("last_seen"),
            "first_seen": info.get("first_seen"),
        }
    return result


def load_donations_map() -> Dict[str, Dict[str, int]]:
    raw = load_donations_memory()
    players = raw.get("players", {}) if isinstance(raw, dict) else {}
    result: Dict[str, Dict[str, int]] = {}
    for raw_tag, info in players.items():
        tag = normalize_tag(raw_tag)
        info = info if isinstance(info, dict) else {}
        result[tag] = {
            "donations": int(info.get("donations", 0) or 0),
            "received": int(info.get("received", 0) or 0),
        }
    return result


def load_strikes_map() -> Dict[str, int]:
    raw = load_strikes_raw()
    players = raw.get("players", {}) if isinstance(raw, dict) else {}
    result: Dict[str, int] = {}
    if not isinstance(players, dict):
        return result
    for key, value in players.items():
        try:
            result[normalize_name(key)] = int(value or 0)
        except Exception:
            result[normalize_name(key)] = 0
    return result


def score_history_rows() -> List[Dict[str, Any]]:
    if not SCORE_HISTORY_PATH.exists():
        return []
    try:
        with open(SCORE_HISTORY_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return []


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def latest_score_map() -> Dict[str, Dict[str, Any]]:
    rows = score_history_rows()
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("player_name") or row.get("playername") or "").strip()
        if not name:
            continue
        date = str(row.get("date") or "")
        current = latest.get(normalize_name(name))
        if current is None or date >= current.get("date", ""):
            latest[normalize_name(name)] = {
                "score": parse_float(row.get("score", 0)),
                "trophies": parse_int(row.get("trophies", 0)),
                "date": date,
            }
    return latest


def strikes_for_player(tag: str, name: str) -> int:
    strikes = load_strikes_map()
    return int(strikes.get(normalize_name(name), strikes.get(normalize_name(tag), 0)) or 0)


def build_players_enriched() -> Dict[str, Dict[str, Any]]:
    members = load_current_players()
    donations = load_donations_map()
    scores = latest_score_map()
    enriched: Dict[str, Dict[str, Any]] = {}
    for tag, base in members.items():
        score_entry = scores.get(normalize_name(base.get("name"))) or {}
        donation_entry = donations.get(tag, {"donations": 0, "received": 0})
        enriched[tag] = {
            **base,
            "donations": donation_entry.get("donations", 0),
            "donations_received": donation_entry.get("received", 0),
            "score": score_entry.get("score", 0.0),
            "trophies": score_entry.get("trophies", 0),
            "score_date": score_entry.get("date"),
            "strikes": strikes_for_player(tag, base.get("name", "")),
        }
    return enriched


def build_warning_candidates() -> List[Dict[str, Any]]:
    players = build_players_enriched()
    out: List[Dict[str, Any]] = []
    for tag, p in players.items():
        reasons: List[str] = []
        if p["score"] < STRIKE_THRESHOLD:
            reasons.append(f"Score unter {STRIKE_THRESHOLD}")
        if p["strikes"] >= 2:
            reasons.append("bereits mehrere Strikes vorhanden")
        if reasons:
            out.append({
                "name": p["name"],
                "tag": tag,
                "role": p["role"],
                "score": p["score"],
                "donations": p["donations"],
                "donations_received": p["donations_received"],
                "trophies": p["trophies"],
                "strikes": p["strikes"],
                "reason": "; ".join(reasons),
                "recommended_action": "warning",
            })
    return sorted(out, key=lambda x: (x["score"], -x["strikes"], x["donations"]))


def build_promotion_candidates() -> List[Dict[str, Any]]:
    players = build_players_enriched()
    out: List[Dict[str, Any]] = []
    for tag, p in players.items():
        role = normalize_name(p.get("role", "member"))
        if role not in {"member", "mitglied", ""}:
            continue
        if p["score"] < PROMOTION_SCORE_MIN:
            continue
        if p["donations"] < PROMOTION_DONATIONS_MIN:
            continue
        if p["strikes"] > 0:
            continue
        out.append({
            "name": p["name"],
            "tag": tag,
            "current_role": p.get("role", "member"),
            "score": p["score"],
            "donations": p["donations"],
            "donations_received": p["donations_received"],
            "trophies": p["trophies"],
            "recommended_action": "promote_to_elder",
        })
    return sorted(out, key=lambda x: (-x["score"], -x["donations"], -x["trophies"]))


@app.get("/health")
def health():
    return {"status": "ok", "mode": "json-first"}


@app.get("/summary")
def summary():
    players = build_players_enriched()
    warnings = build_warning_candidates()
    promotions = build_promotion_candidates()
    records = load_records()
    strikes = load_strikes_raw()
    return {
        "status": "ok",
        "mode": "json-first",
        "member_count": len(players),
        "warning_candidates": len(warnings),
        "promotion_candidates": len(promotions),
        "records_available": list(records.keys()) if isinstance(records, dict) else [],
        "strike_week": strikes.get("last_strike_week", []),
    }


@app.get("/players")
def players():
    data = list(build_players_enriched().values())
    return {"players": sorted(data, key=lambda x: x["name"].lower())}


@app.get("/warnings")
def warnings():
    return {"players": build_warning_candidates()}


@app.get("/promotions")
def promotions():
    return {"players": build_promotion_candidates()}


@app.get("/strikes")
def strikes():
    return load_strikes_raw()


@app.get("/records")
def records():
    return load_records()


@app.get("/kicked")
def kicked():
    return {"players": load_kicked_players()}


@app.get("/player/{player_tag}")
def player(player_tag: str):
    tag = normalize_tag(player_tag)
    players = build_players_enriched()
    if tag not in players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")
    return players[tag]
