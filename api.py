from fastapi import FastAPI, HTTPException
from pathlib import Path
import json
import pandas as pd
from typing import Any, Dict, List

app = FastAPI(title="Clash Royale Clan Management API", version="1.0.0")

BASE_DIR = Path(__file__).parent.resolve()
STRIKES_PATH = BASE_DIR / "strikes.json"
RECORDS_PATH = BASE_DIR / "records.json"
SCORE_HISTORY_PATH = BASE_DIR / "score_history.csv"
MEMBER_MEMORY_PATH = BASE_DIR / "member_memory.json"
KICKED_PLAYERS_PATH = BASE_DIR / "kicked_players.json"
TOP_DECKS_PATH = BASE_DIR / "top_decks.json"

STRIKE_THRESHOLD = 50
DROPPER_THRESHOLD = 130
MIN_PARTICIPATION = 3
PROMOTION_SCORE_MIN = 85
PROMOTION_DONATIONS_MIN = 50


def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def get_latest_csv() -> Path:
    uploads = BASE_DIR / "uploads"
    csvs = sorted(uploads.glob("*.csv"), key=lambda p: p.stat().st_mtime)
    if not csvs:
        raise FileNotFoundError("Keine CSV-Datei in uploads gefunden")
    return csvs[-1]


def latest_fame_columns(df: pd.DataFrame) -> List[str]:
    cols = [c for c in df.columns if str(c).startswith("s") and str(c).endswith("fame")]
    return sorted(cols, reverse=True)


def score_from_row(row: pd.Series) -> float:
    wars_with_participation = int(row.get("playercontributioncount", 0) or 0)
    wars_in_window = int(row.get("playerparticipatingcount", 0) or 0)
    total_decks = int(row.get("playertotaldecksused", 0) or 0)
    max_possible_decks = wars_with_participation * 4
    attendance = wars_with_participation / wars_in_window if wars_in_window > 0 else 0.0
    deck_usage = total_decks / max_possible_decks if max_possible_decks > 0 else 0.0
    return round(attendance * deck_usage * 100, 2)


def fame_per_deck_from_row(row: pd.Series) -> int:
    fame_cols = latest_fame_columns(pd.DataFrame([row]))[:4]
    rolling_fame = sum(int(row.get(c, 0) or 0) for c in fame_cols)
    deck_cols = [str(c).replace("fame", "decksused") for c in fame_cols]
    rolling_decks = sum(int(row.get(c, 0) or 0) for c in deck_cols)
    if rolling_decks <= 0:
        return 0
    return int(round(rolling_fame / rolling_decks))


def player_tag_map(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    result = {}
    for _, row in df.iterrows():
        tag = str(row.get("playertag", "")).strip().upper()
        if not tag:
            continue
        result[tag] = {
            "name": row.get("playername", "Unbekannt"),
            "role": row.get("playerrole", "member"),
            "donations": int(row.get("playerdonations", 0) or 0),
            "donations_received": int(row.get("playerdonationsreceived", 0) or 0),
            "trophies": int(row.get("playertrophies", 0) or 0),
            "participation_count": int(row.get("playercontributioncount", 0) or 0),
            "wars_in_window": int(row.get("playerparticipatingcount", 0) or 0),
            "total_decks": int(row.get("playertotaldecksused", 0) or 0),
            "score": score_from_row(row),
            "fame_per_deck": fame_per_deck_from_row(row),
        }
    return result


def load_current_players() -> Dict[str, Dict[str, Any]]:
    csv_path = get_latest_csv()
    df = pd.read_csv(csv_path)
    mask = df["playeriscurrentmember"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
    active = df[mask].copy()
    return player_tag_map(active)


def load_strikes_map() -> Dict[str, Any]:
    raw = load_json(STRIKES_PATH, {"players": {}})
    players = raw.get("players", {}) if isinstance(raw, dict) else {}
    return players if isinstance(players, dict) else {}


def build_warning_candidates() -> List[Dict[str, Any]]:
    players = load_current_players()
    strikes = load_strikes_map()
    out = []
    for tag, p in players.items():
        score = p["score"]
        fame_per_deck = p["fame_per_deck"]
        participation = p["participation_count"]
        current_strikes = strikes.get(tag, strikes.get(p["name"], 0))
        if isinstance(current_strikes, dict):
            current_strikes = current_strikes.get("count", 0)
        if participation <= MIN_PARTICIPATION:
            continue
        reasons = []
        if score < STRIKE_THRESHOLD:
            reasons.append(f"Score unter {STRIKE_THRESHOLD}")
        if 0 < fame_per_deck < DROPPER_THRESHOLD:
            reasons.append(f"Ø Punkte/Deck unter {DROPPER_THRESHOLD}")
        if reasons:
            out.append({
                "name": p["name"],
                "tag": tag,
                "role": p["role"],
                "score": score,
                "fame_per_deck": fame_per_deck,
                "donations": p["donations"],
                "participation_count": participation,
                "strikes": int(current_strikes or 0),
                "reason": "; ".join(reasons),
                "recommended_action": "warning"
            })
    return sorted(out, key=lambda x: (x["score"], x["fame_per_deck"]))


def build_promotion_candidates() -> List[Dict[str, Any]]:
    players = load_current_players()
    strikes = load_strikes_map()
    out = []
    for tag, p in players.items():
        role = str(p["role"]).lower()
        current_strikes = strikes.get(tag, strikes.get(p["name"], 0))
        if isinstance(current_strikes, dict):
            current_strikes = current_strikes.get("count", 0)
        if role != "member":
            continue
        if p["participation_count"] <= MIN_PARTICIPATION:
            continue
        if p["score"] < PROMOTION_SCORE_MIN:
            continue
        if p["donations"] < PROMOTION_DONATIONS_MIN:
            continue
        if int(current_strikes or 0) > 0:
            continue
        out.append({
            "name": p["name"],
            "tag": tag,
            "current_role": role,
            "score": p["score"],
            "fame_per_deck": p["fame_per_deck"],
            "donations": p["donations"],
            "participation_count": p["participation_count"],
            "recommended_action": "promote_to_elder"
        })
    return sorted(out, key=lambda x: (-x["score"], -x["donations"]))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/summary")
def summary():
    players = load_current_players()
    warnings = build_warning_candidates()
    promotions = build_promotion_candidates()
    records = load_json(RECORDS_PATH, {})
    return {
        "status": "ok",
        "member_count": len(players),
        "warning_candidates": len(warnings),
        "promotion_candidates": len(promotions),
        "records_available": list(records.keys()) if isinstance(records, dict) else []
    }


@app.get("/warnings")
def warnings():
    return {"players": build_warning_candidates()}


@app.get("/promotions")
def promotions():
    return {"players": build_promotion_candidates()}


@app.get("/strikes")
def strikes():
    return load_json(STRIKES_PATH, {"players": {}})


@app.get("/player/{player_tag}")
def player(player_tag: str):
    tag = player_tag.strip().upper()
    if not tag.startswith("#"):
        tag = f"#{tag}"
    players = load_current_players()
    if tag not in players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")
    strikes = load_strikes_map()
    payload = players[tag]
    current_strikes = strikes.get(tag, strikes.get(payload["name"], 0))
    if isinstance(current_strikes, dict):
        current_strikes = current_strikes.get("count", 0)
    payload = dict(payload)
    payload["tag"] = tag
    payload["strikes"] = int(current_strikes or 0)
    return payload
