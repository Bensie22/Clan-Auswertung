import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from app.utils import normalize_tag, normalize_name, parse_float, parse_int

BASE_DIR = Path(__file__).parent.parent.resolve()

STRIKES_PATH       = BASE_DIR / "strikes.json"
RECORDS_PATH       = BASE_DIR / "records.json"
SCORE_HISTORY_PATH = BASE_DIR / "score_history.csv"
MEMBER_MEMORY_PATH = BASE_DIR / "member_memory.json"
KICKED_PLAYERS_PATH    = BASE_DIR / "kicked_players.json"
DONATIONS_MEMORY_PATH  = BASE_DIR / "donations_memory.json"
PLAYER_STATS_PATH  = BASE_DIR / "player_stats.json"
TOP_DECKS_PATH     = BASE_DIR / "top_decks.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


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


def load_player_stats() -> Dict[str, Dict[str, Any]]:
    raw = load_json(PLAYER_STATS_PATH, [])
    result: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, list):
        for entry in raw:
            tag = normalize_tag(entry.get("tag", ""))
            if tag:
                result[tag] = entry
    return result


def load_top_decks() -> Dict[str, Any]:
    return load_json(TOP_DECKS_PATH, {"decks": {}, "_metadata": {"last_battles": {}}, "_opponent_decks": {}})


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


def score_history_by_player() -> Dict[str, List[Dict[str, Any]]]:
    rows = score_history_rows()
    by_player: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        name = str(row.get("player_name") or "").strip()
        if not name:
            continue
        key = normalize_name(name)
        if key not in by_player:
            by_player[key] = []
        by_player[key].append({
            "date": str(row.get("date") or ""),
            "score": parse_float(row.get("score", 0)),
            "trophies": parse_int(row.get("trophies", 0)),
            "name": name,
        })
    for key in by_player:
        by_player[key].sort(key=lambda x: x["date"])
    return by_player


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
