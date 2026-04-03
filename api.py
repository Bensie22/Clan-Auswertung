from fastapi import FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from pathlib import Path
import json
import pandas as pd
from typing import Any, Dict, List

app = FastAPI(
    title="Clash Royale Clan Management API",
    version="1.0.0",
    description="API für Clanführung, Warnungen, Beförderungen und Spielerübersichten."
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Clash Royale Clan Management API",
        version="1.0.0",
        description=(
            "Diese API liefert aktuelle Clanführungsdaten für Clash Royale. "
            "Sie stellt Health-Check, Clan-Zusammenfassung, Verwarnungskandidaten, "
            "Beförderungskandidaten, Strike-Status und Spielerberichte bereit."
        ),
        routes=app.routes,
    )
    openapi_schema["servers"] = [
        {"url": "https://clan-gpt-api.onrender.com"}
    ]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

BASE_DIR = Path(__file__).parent.resolve()
STRIKES_PATH = BASE_DIR / "strikes.json"
RECORDS_PATH = BASE_DIR / "records.json"
SCORE_HISTORY_PATH = BASE_DIR / "scorehistory.csv"
KICKED_PLAYERS_PATH = BASE_DIR / "kickedplayers.json"
TOP_DECKS_PATH = BASE_DIR / "topdecks.json"

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
    fame_cols = [c for c in row.index if str(c).startswith("s") and str(c).endswith("fame")]
    fame_cols = sorted(fame_cols, reverse=True)[:4]
    rolling_fame = sum(int(row.get(c, 0) or 0) for c in fame_cols)
    deck_cols = [str(c).replace("fame", "decksused") for c in fame_cols]
    rolling_decks = sum(int(row.get(c, 0) or 0) for c in deck_cols)
    if rolling_decks <= 0:
        return 0
    return int(round(rolling_fame / rolling_decks))



def player_tag_map(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        tag = str(row.get("playertag", "")).strip().upper()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
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
    out: List[Dict[str, Any]] = []
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
                "recommended_action": "warning",
            })
    return sorted(out, key=lambda x: (x["score"], x["fame_per_deck"]))



def build_promotion_candidates() -> List[Dict[str, Any]]:
    players = load_current_players()
    strikes = load_strikes_map()
    out: List[Dict[str, Any]] = []
    for tag, p in players.items():
        role = str(p["role"] or "member").lower()
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
            "recommended_action": "promote_to_elder",
        })
    return sorted(out, key=lambda x: (-x["score"], -x["donations"]))


@app.get("/health", summary="Health Check", description="Prüft, ob die API erreichbar ist.")
def health():
    return {"status": "ok"}


@app.get("/summary", summary="Clan-Zusammenfassung", description="Liefert eine Kurz-Zusammenfassung zur aktuellen Clanlage.")
def summary():
    try:
        players = load_current_players()
        warnings = build_warning_candidates()
        promotions = build_promotion_candidates()
        records = load_json(RECORDS_PATH, {})
        return {
            "status": "ok",
            "member_count": len(players),
            "warning_candidates": len(warnings),
            "promotion_candidates": len(promotions),
            "records_available": list(records.keys()) if isinstance(records, dict) else [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Summary failed: {repr(e)}")


@app.get("/warnings", summary="Warnungskandidaten", description="Liefert aktuelle Spieler, die für eine Verwarnung infrage kommen.")
def warnings():
    try:
        return {"players": build_warning_candidates()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Warnings failed: {repr(e)}")


@app.get("/promotions", summary="Beförderungskandidaten", description="Liefert aktuelle Spieler, die für eine Beförderung infrage kommen.")
def promotions():
    try:
        result = {"players": build_promotion_candidates()}
        print("PROMOTIONS RESULT:", result)
        return result
    except Exception as e:
        print("PROMOTIONS ERROR:", repr(e))
        raise HTTPException(status_code=500, detail=f"Promotions failed: {repr(e)}")


@app.get("/strikes", summary="Strike-Status", description="Liefert den aktuellen Strike-Stand aus der Strike-Datei.")
def strikes():
    try:
        return load_json(STRIKES_PATH, {"players": {}})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Strikes failed: {repr(e)}")


@app.get("/player/{player_tag}", summary="Spielerbericht", description="Liefert einen Bericht zu einem bestimmten Spieler anhand seines Tags.")
def player(player_tag: str):
    try:
        tag = player_tag.strip().upper()
        if not tag.startswith("#"):
            tag = f"#{tag}"
        players = load_current_players()
        if tag not in players:
            raise HTTPException(status_code=404, detail="Spieler nicht gefunden")
        strikes = load_strikes_map()
        payload = dict(players[tag])
        current_strikes = strikes.get(tag, strikes.get(payload["name"], 0))
        if isinstance(current_strikes, dict):
            current_strikes = current_strikes.get("count", 0)
        payload["tag"] = tag
        payload["strikes"] = int(current_strikes or 0)
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Player failed: {repr(e)}")
