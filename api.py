from fastapi import FastAPI, HTTPException, Query
from fastapi.openapi.utils import get_openapi
from pathlib import Path
from typing import Any, Dict, List, Optional
import csv
import json
import os
import requests as http_requests
from datetime import datetime, timezone

app = FastAPI(title="Clash Royale Clan Management API", version="3.0.0")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Clash Royale Clan Management API",
        version="3.0.0",
        description="JSON-first API für Clanführung, Warnungen, Beförderungen, Kriegsanalyse und Spielerübersichten.",
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
PLAYER_STATS_PATH = BASE_DIR / "player_stats.json"
TOP_DECKS_PATH = BASE_DIR / "top_decks.json"

STRIKE_THRESHOLD = 50
PROMOTION_SCORE_MIN = 85
PROMOTION_DONATIONS_MIN = 50
NAME_STRIKE_LOOKUP = {"amp", "gang", "bequemo"}

APP_CONFIG = {
    "STRIKE_THRESHOLD": 50,
    "DROPPER_THRESHOLD": 130,
    "MIN_PARTICIPATION": 3,
    "BADGE_STARK_SCORE": 90,
    "BADGE_STARK_FAME": 185,
    "BADGE_STABIL_SCORE": 75,
    "BADGE_STABIL_FAME": 145,
    "TIER_SEHR_STARK": 95,
    "TIER_SOLIDE": 80,
    "CLAN_RELIABLE_GREEN": 85,
    "CLAN_RELIABLE_YELLOW": 70,
}

CLAN_TAG_RAW = "#Y9YQC8UG"
CLAN_TAG_ENCODED = "%23Y9YQC8UG"
CR_API_BASE = "https://api.clashroyale.com/v1"


# ── Basis-Hilfsfunktionen ────────────────────────────────────────────────────

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


# ── Datei-Loader ─────────────────────────────────────────────────────────────

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


# ── Erweiterte Hilfsfunktionen ───────────────────────────────────────────────

def cr_api_get(path: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("CR_API_KEY", "")
    if not api_key:
        return None
    try:
        resp = http_requests.get(
            f"{CR_API_BASE}{path}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def fetch_riverracelog() -> Optional[List[Dict[str, Any]]]:
    """Ruft den River-Race-Verlauf live von der CR-API ab."""
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/riverracelog")
    if data is None:
        return None
    return data.get("items", [])


def fetch_currentriverrace() -> Optional[Dict[str, Any]]:
    """Ruft den aktuellen River-Race live von der CR-API ab."""
    return cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/currentriverrace")


def compute_trend(scores: List[float]) -> str:
    return "".join([
        "🟢" if s >= APP_CONFIG["TIER_SOLIDE"] else
        "🟡" if s >= APP_CONFIG["STRIKE_THRESHOLD"] else
        "🔴"
        for s in scores[-6:]
    ])


def compute_streak(scores: List[float]) -> int:
    streak = 0
    for s in reversed(scores):
        if s >= 100.0:
            streak += 1
        else:
            break
    return streak


def get_focus_badge(score: float, fame_per_deck: float, participation_count: int) -> Dict[str, str]:
    if participation_count <= APP_CONFIG["MIN_PARTICIPATION"]:
        return {
            "badge": "🌱 neu dabei",
            "label": "NEWCOMER",
            "description": "Noch im Welpenschutz – Bewertung startet nach 3 Kriegen",
        }
    if score >= APP_CONFIG["BADGE_STARK_SCORE"] and fame_per_deck >= APP_CONFIG["BADGE_STARK_FAME"]:
        return {
            "badge": "⭐ stark",
            "label": "STARK",
            "description": "Sehr starke Leistung in Krieg und Deck-Qualität",
        }
    if score >= APP_CONFIG["BADGE_STABIL_SCORE"] and fame_per_deck >= APP_CONFIG["BADGE_STABIL_FAME"]:
        return {
            "badge": "🛡️ stabil",
            "label": "STABIL",
            "description": "Solider und verlässlicher Mitspieler",
        }
    if fame_per_deck < APP_CONFIG["DROPPER_THRESHOLD"] and participation_count > APP_CONFIG["MIN_PARTICIPATION"]:
        return {
            "badge": "⚠️ ausbaufähig",
            "label": "DROPPER",
            "description": "Niedrige Punkte pro Deck – Deck-Qualität verbessern",
        }
    return {
        "badge": "👀 auffällig",
        "label": "WATCH",
        "description": "Im Auge behalten",
    }


def build_promotion_status(p: Dict[str, Any]) -> Dict[str, Any]:
    score = p.get("score", 0)
    donations = p.get("donations", 0)
    strikes = p.get("strikes", 0)
    role = normalize_name(p.get("role", "member"))

    missing_score = max(0.0, round(PROMOTION_SCORE_MIN - score, 2))
    missing_donations = max(0, PROMOTION_DONATIONS_MIN - donations)

    eligible = (
        role in {"member", "mitglied", ""}
        and score >= PROMOTION_SCORE_MIN
        and donations >= PROMOTION_DONATIONS_MIN
        and strikes == 0
    )

    score_progress = min(100.0, round(score / PROMOTION_SCORE_MIN * 100, 1))
    donation_progress = min(100.0, round(donations / PROMOTION_DONATIONS_MIN * 100, 1))
    strike_ok = strikes == 0
    overall_progress = round((score_progress + donation_progress + (100.0 if strike_ok else 0.0)) / 3, 1)

    missing_items = []
    if missing_score > 0:
        missing_items.append(f"{missing_score}% Score fehlen")
    if missing_donations > 0:
        missing_items.append(f"{missing_donations} Spenden fehlen")
    if strikes > 0:
        missing_items.append(f"{strikes} Strike(s) vorhanden")

    return {
        "eligible": eligible,
        "current_role": p.get("role", "member"),
        "score": score,
        "score_progress_pct": score_progress,
        "donations": donations,
        "donation_progress_pct": donation_progress,
        "strikes": strikes,
        "strike_free": strike_ok,
        "overall_progress_pct": overall_progress,
        "missing": missing_items,
        "summary": (
            "Bereit für Beförderung zu Elder! 🎉"
            if eligible
            else ("Fehlt: " + "; ".join(missing_items) if missing_items else "Bereits befördert oder nicht geeignet")
        ),
    }


def calculate_teamplay_score_from_stats(players: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(players)
    if total == 0:
        return {"score": 0, "donors": 0, "leecher": 0, "sleeper": 0, "signal": "unbekannt", "total_players": 0}

    donors = sum(1 for p in players if p.get("donations", 0) > 0)
    leecher = sum(
        1 for p in players
        if p.get("donations", 0) == 0
        and p.get("donations_received", 0) > 0
        and p.get("participation_count", 0) > APP_CONFIG["MIN_PARTICIPATION"]
    )
    sleeper = sum(1 for p in players if p.get("donations", 0) == 0 and p.get("donations_received", 0) == 0)

    donor_share = (donors / total) * 100
    leecher_share = (leecher / total) * 100
    sleeper_share = (sleeper / total) * 100

    score = round(max(0, min(100, donor_share - (leecher_share * 0.7) - (sleeper_share * 0.3))))
    signal = "sehr gut 🟢" if score >= 60 else "okay 🟡" if score >= 35 else "kritisch 🔴"

    return {
        "score": score,
        "signal": signal,
        "donors": donors,
        "leecher": leecher,
        "sleeper": sleeper,
        "total_players": total,
        "donor_share_pct": round(donor_share, 1),
        "leecher_share_pct": round(leecher_share, 1),
        "sleeper_share_pct": round(sleeper_share, 1),
    }


# ── Kern-Builder ─────────────────────────────────────────────────────────────

def build_players_enriched() -> Dict[str, Dict[str, Any]]:
    members = load_current_players()
    donations = load_donations_map()
    scores = latest_score_map()
    stats = load_player_stats()
    enriched: Dict[str, Dict[str, Any]] = {}
    for tag, base in members.items():
        score_entry = scores.get(normalize_name(base.get("name"))) or {}
        donation_entry = donations.get(tag, {"donations": 0, "received": 0})
        stat_entry = stats.get(tag, {})
        enriched[tag] = {
            **base,
            "donations": stat_entry.get("donations", donation_entry.get("donations", 0)),
            "donations_received": stat_entry.get("donations_received", donation_entry.get("received", 0)),
            "score": stat_entry.get("score", score_entry.get("score", 0.0)),
            "trophies": stat_entry.get("trophies", score_entry.get("trophies", 0)),
            "score_date": score_entry.get("date"),
            "strikes": strikes_for_player(tag, base.get("name", "")),
            "fame_per_deck": stat_entry.get("fame_per_deck", 0),
            "participation_count": stat_entry.get("participation_count", 0),
            "total_decks": stat_entry.get("total_decks", 0),
            "wars_in_window": stat_entry.get("wars_in_window", 0),
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


# ════════════════════════════════════════════════════════════════════════════
# BESTEHENDE ENDPUNKTE
# ════════════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 1: CLAN-KRIEG VERLAUF
# ════════════════════════════════════════════════════════════════════════════

@app.get("/warlog")
def warlog():
    """Kriegsverlauf – live von CR-API (Fame, Decks, Boat Attacks pro Spieler) oder CSV als Fallback."""
    items = fetch_riverracelog()
    if items:
        wars = []
        for item in items:
            standings = item.get("standings", [])
            our_standing = next(
                (s for s in standings if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
            )
            our_rank = next(
                (i + 1 for i, s in enumerate(standings) if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
            )
            if not our_standing:
                continue
            clan = our_standing.get("clan", {})
            participants = clan.get("participants", [])
            total_decks = sum(p.get("decksUsed", 0) for p in participants)
            total_fame = clan.get("fame", 0)
            wars.append({
                "season_id": item.get("seasonId"),
                "section_index": item.get("sectionIndex"),
                "created_date": item.get("createdDate"),
                "our_rank": our_rank,
                "total_clans": len(standings),
                "our_fame": total_fame,
                "trophy_change": our_standing.get("trophyChange", 0),
                "total_decks_used": total_decks,
                "avg_fame_per_deck": round(total_fame / total_decks) if total_decks > 0 else 0,
                "participants_count": len(participants),
                "players": sorted([
                    {
                        "name": p.get("name"),
                        "tag": p.get("tag"),
                        "fame": p.get("fame", 0),
                        "decks_used": p.get("decksUsed", 0),
                        "boat_attacks": p.get("boatAttacks", 0),
                        "repair_points": p.get("repairPoints", 0),
                    }
                    for p in participants
                ], key=lambda x: -x["fame"]),
            })
        return {"source": "live", "wars": wars, "total_recorded": len(wars)}

    # Fallback: CSV
    rows = score_history_rows()
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        date = str(row.get("date") or "").strip()
        if not date:
            continue
        if date not in by_date:
            by_date[date] = []
        by_date[date].append({
            "name": str(row.get("player_name") or "").strip(),
            "score": parse_float(row.get("score", 0)),
            "trophies": parse_int(row.get("trophies", 0)),
        })
    wars = []
    for date, date_players in sorted(by_date.items()):
        scores = [p["score"] for p in date_players]
        wars.append({
            "date": date,
            "participants": len(date_players),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "players": sorted(date_players, key=lambda x: -x["score"]),
        })
    return {"source": "csv", "wars": list(reversed(wars)), "total_recorded": len(wars)}


@app.get("/warlog/current")
def warlog_current():
    """Aktuelle Kriegsübersicht aller Spieler mit Score, Fame/Deck und Badge."""
    stats = load_player_stats()
    enriched_players = list(build_players_enriched().values())

    result = []
    for p in enriched_players:
        focus = get_focus_badge(
            p.get("score", 0),
            p.get("fame_per_deck", 0),
            p.get("participation_count", 0),
        )
        result.append({
            "name": p["name"],
            "tag": p.get("tag"),
            "role": p.get("role"),
            "score": p.get("score", 0),
            "fame_per_deck": p.get("fame_per_deck", 0),
            "total_decks": p.get("total_decks", 0),
            "participation_count": p.get("participation_count", 0),
            "wars_in_window": p.get("wars_in_window", 0),
            "focus_badge": focus["badge"],
            "focus_label": focus["label"],
        })

    scores = [p["score"] for p in result]
    fame_values = [p["fame_per_deck"] for p in result if p["fame_per_deck"] > 0]

    return {
        "clan_avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "clan_avg_fame_per_deck": round(sum(fame_values) / len(fame_values), 1) if fame_values else 0,
        "total_members": len(result),
        "players": sorted(result, key=lambda x: -x["score"]),
    }


@app.get("/player/{player_tag}/warlog")
def player_warlog(player_tag: str):
    """Kriegsverlauf eines Spielers – live (Fame, Decks, Boat Attacks) oder CSV als Fallback."""
    tag = normalize_tag(player_tag)
    tag_bare = tag.lstrip("#")
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    player_name = all_players[tag]["name"]

    # Live-Versuch
    items = fetch_riverracelog()
    if items:
        wars = []
        for item in items:
            standings = item.get("standings", [])
            our_standing = next(
                (s for s in standings if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
            )
            if not our_standing:
                continue
            participants = our_standing.get("clan", {}).get("participants", [])
            player_entry = next(
                (p for p in participants if p.get("tag", "").lstrip("#") == tag_bare), None
            )
            if not player_entry:
                continue
            wars.append({
                "season_id": item.get("seasonId"),
                "created_date": item.get("createdDate"),
                "our_rank": next(
                    (i + 1 for i, s in enumerate(standings) if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
                ),
                "fame": player_entry.get("fame", 0),
                "decks_used": player_entry.get("decksUsed", 0),
                "boat_attacks": player_entry.get("boatAttacks", 0),
                "repair_points": player_entry.get("repairPoints", 0),
                "trophy_change": our_standing.get("trophyChange", 0),
            })
        if wars:
            total_fame = sum(w["fame"] for w in wars)
            total_decks = sum(w["decks_used"] for w in wars)
            return {
                "source": "live",
                "tag": tag,
                "name": player_name,
                "wars": wars,
                "total_wars": len(wars),
                "total_fame": total_fame,
                "avg_fame_per_deck": round(total_fame / total_decks) if total_decks > 0 else 0,
            }

    # Fallback: CSV
    history = score_history_by_player()
    entries = history.get(normalize_name(player_name), [])
    if not entries:
        return {"tag": tag, "name": player_name, "wars": [], "message": "Keine Kriegsdaten vorhanden"}
    wars_csv = []
    for i, entry in enumerate(entries):
        delta = round(entry["score"] - entries[i - 1]["score"], 2) if i > 0 else None
        wars_csv.append({
            "date": entry["date"],
            "score": entry["score"],
            "trophies": entry["trophies"],
            "delta": delta,
            "trend_symbol": "🟢" if entry["score"] >= 80 else "🟡" if entry["score"] >= 50 else "🔴",
        })
    return {
        "source": "csv",
        "tag": tag,
        "name": player_name,
        "wars": list(reversed(wars_csv)),
        "total_wars": len(wars_csv),
        "avg_score": round(sum(e["score"] for e in entries) / len(entries), 2),
    }


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 2: SPIELER-TIEFENANALYSE
# ════════════════════════════════════════════════════════════════════════════

@app.get("/player/{player_tag}/history")
def player_history(player_tag: str):
    """Vollständige Score-Historie eines Spielers mit Trend und Streak."""
    tag = normalize_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    player_name = all_players[tag]["name"]
    history = score_history_by_player()
    entries = history.get(normalize_name(player_name), [])
    scores = [e["score"] for e in entries]

    trend = compute_trend(scores) if scores else ""
    streak = compute_streak(scores)

    return {
        "tag": tag,
        "name": player_name,
        "entries": list(reversed(entries)),
        "trend": trend,
        "streak": streak,
        "streak_badge": f"🔥 {streak}x perfekt" if streak >= 3 else None,
        "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "best_score": max(scores) if scores else 0,
        "worst_score": min(scores) if scores else 0,
    }


@app.get("/player/{player_tag}/decks")
def player_decks(player_tag: str):
    """Decks, die ein Spieler genutzt hat, mit Winrate pro Deck."""
    tag = normalize_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    # Tags in top_decks.json sind ohne '#'
    tag_bare = tag.lstrip("#")

    top_decks_data = load_top_decks()
    decks_dict = top_decks_data.get("decks", {})

    player_decks_list = []
    for deck_key, deck_data in decks_dict.items():
        if not isinstance(deck_data, dict):
            continue
        deck_tags = [str(t) for t in deck_data.get("tags", [])]
        if tag_bare not in deck_tags:
            continue

        wins = parse_int(deck_data.get("wins", 0))
        losses = parse_int(deck_data.get("losses", 0))
        total = wins + losses
        winrate = round(wins / total * 100, 1) if total > 0 else 0

        player_decks_list.append({
            "deck_key": deck_key,
            "cards": [c.get("name") for c in deck_data.get("cards", []) if isinstance(c, dict)],
            "wins": wins,
            "losses": losses,
            "total_matches": total,
            "winrate_pct": winrate,
        })

    player_decks_list.sort(key=lambda x: -x["total_matches"])

    return {
        "tag": tag,
        "name": all_players[tag]["name"],
        "decks": player_decks_list[:20],
        "total_decks_found": len(player_decks_list),
    }


@app.get("/player/{player_tag}/focus")
def player_focus(player_tag: str):
    """Fokus-Badge und Welpenschutz-Status eines Spielers."""
    tag = normalize_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))

    history = score_history_by_player()
    entries = history.get(normalize_name(p["name"]), [])
    scores = [e["score"] for e in entries]

    is_welpenschutz = p.get("participation_count", 0) <= APP_CONFIG["MIN_PARTICIPATION"]
    wars_until_evaluated = max(0, APP_CONFIG["MIN_PARTICIPATION"] + 1 - p.get("participation_count", 0))

    return {
        "tag": tag,
        "name": p["name"],
        "role": p.get("role"),
        "score": p.get("score", 0),
        "fame_per_deck": p.get("fame_per_deck", 0),
        "participation_count": p.get("participation_count", 0),
        "focus": focus,
        "welpenschutz": is_welpenschutz,
        "wars_until_evaluated": wars_until_evaluated if is_welpenschutz else 0,
        "trend": compute_trend(scores) if scores else "",
        "streak": compute_streak(scores),
    }


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 4: AKTIVITÄT & DONATIONEN
# ════════════════════════════════════════════════════════════════════════════

@app.get("/players/activity")
def players_activity():
    """Alle Spieler mit letztem Kampf, Beitrittsdatum und Teilnahmequote."""
    all_players = build_players_enriched()
    top_decks_data = load_top_decks()
    last_battles = top_decks_data.get("_metadata", {}).get("last_battles", {})

    now = datetime.now(timezone.utc)
    result = []
    for tag, p in all_players.items():
        last_battle_raw = last_battles.get(tag)
        last_battle = None
        days_since_battle = None
        if last_battle_raw:
            try:
                dt = datetime.strptime(last_battle_raw, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
                last_battle = dt.isoformat()
                days_since_battle = (now - dt).days
            except Exception:
                pass

        result.append({
            "name": p["name"],
            "tag": tag,
            "role": p.get("role"),
            "first_seen": p.get("first_seen"),
            "last_seen": p.get("last_seen"),
            "last_battle": last_battle,
            "days_since_last_battle": days_since_battle,
            "participation_count": p.get("participation_count", 0),
            "wars_in_window": p.get("wars_in_window", 0),
            "score": p.get("score", 0),
        })

    result.sort(
        key=lambda x: (x["days_since_last_battle"] is None, x.get("days_since_last_battle") or 0),
        reverse=True,
    )
    return {"players": result, "total": len(result)}


@app.get("/players/inaktiv")
def players_inaktiv(days: int = Query(default=3, ge=1, le=30, description="Inaktiv seit X Tagen")):
    """Spieler, die seit mindestens X Tagen keinen Kampf gespielt haben."""
    all_players = build_players_enriched()
    top_decks_data = load_top_decks()
    last_battles = top_decks_data.get("_metadata", {}).get("last_battles", {})

    now = datetime.now(timezone.utc)
    inaktiv = []
    for tag, p in all_players.items():
        last_battle_raw = last_battles.get(tag)
        days_since = None
        last_battle = None
        if last_battle_raw:
            try:
                dt = datetime.strptime(last_battle_raw, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
                days_since = (now - dt).days
                last_battle = dt.isoformat()
            except Exception:
                pass

        if days_since is None or days_since >= days:
            inaktiv.append({
                "name": p["name"],
                "tag": tag,
                "role": p.get("role"),
                "last_battle": last_battle,
                "days_since_last_battle": days_since,
                "score": p.get("score", 0),
                "strikes": p.get("strikes", 0),
                "status": "nie gespielt" if days_since is None else f"seit {days_since} Tagen inaktiv",
            })

    inaktiv.sort(
        key=lambda x: (x["days_since_last_battle"] is None, x.get("days_since_last_battle") or 0),
        reverse=True,
    )
    return {"filter_days": days, "count": len(inaktiv), "players": inaktiv}


@app.get("/players/donations")
def players_donations():
    """Spenden-Ranking mit Kategorisierung (Spender, Schmarotzer, Schläfer)."""
    all_players = list(build_players_enriched().values())

    result = []
    for p in all_players:
        donations = p.get("donations", 0)
        received = p.get("donations_received", 0)
        ratio = round(donations / received, 2) if received > 0 else None

        if donations > 0 and received > 0:
            category = "🤝 Ausgewogen"
        elif donations > 0 and received == 0:
            category = "💪 Spender"
        elif donations == 0 and received > 0:
            category = "📦 Schmarotzer"
        else:
            category = "💤 Schläfer"

        result.append({
            "name": p["name"],
            "tag": p.get("tag"),
            "role": p.get("role"),
            "donations": donations,
            "donations_received": received,
            "donation_ratio": ratio,
            "category": category,
        })

    result.sort(key=lambda x: (-x["donations"], x["donations_received"]))
    return {
        "players": result,
        "top_donor": result[0]["name"] if result else None,
        "total_donated": sum(p["donations"] for p in result),
        "total_received": sum(p["donations_received"] for p in result),
    }


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 5: CLAN-BEWERTUNGEN
# ════════════════════════════════════════════════════════════════════════════

@app.get("/analytics/teamplay")
def analytics_teamplay():
    """Teamplay-Score: Donor/Leecher/Schläfer-Verteilung und Gesamtbewertung."""
    all_players = list(build_players_enriched().values())
    return calculate_teamplay_score_from_stats(all_players)


@app.get("/analytics/clan-quality")
def analytics_clan_quality():
    """Clan-Qualität: Durchschnittliche Fame/Deck und Zuverlässigkeitssignal."""
    all_players = list(build_players_enriched().values())
    clan_records = load_records()

    fame_values = [p.get("fame_per_deck", 0) for p in all_players if p.get("fame_per_deck", 0) > 0]
    scores = [p.get("score", 0) for p in all_players]

    avg_fame = round(sum(fame_values) / len(fame_values), 1) if fame_values else 0
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0

    quality_signal = (
        "⭐ stark 🟢" if avg_fame >= APP_CONFIG["BADGE_STARK_FAME"] else
        "🛡️ stabil 🟡" if avg_fame >= APP_CONFIG["BADGE_STABIL_FAME"] else
        "⚠️ ausbaufähig 🔴"
    )
    reliability_signal = (
        "sehr zuverlässig 🟢" if avg_score >= APP_CONFIG["CLAN_RELIABLE_GREEN"] else
        "okay 🟡" if avg_score >= APP_CONFIG["CLAN_RELIABLE_YELLOW"] else
        "kritisch 🔴"
    )

    return {
        "avg_fame_per_deck": avg_fame,
        "avg_score_pct": avg_score,
        "quality_signal": quality_signal,
        "reliability_signal": reliability_signal,
        "record_clan_quality": clan_records.get("clan_quality", {}).get("val") if isinstance(clan_records.get("clan_quality"), dict) else None,
        "record_war_rank": clan_records.get("clan_war_rank"),
        "total_active_players": len(all_players),
    }


@app.get("/players/leaderboard")
def players_leaderboard():
    """Vollrangliste aller Spieler nach Score, Fame/Deck und Trophäen."""
    all_players = build_players_enriched()
    history = score_history_by_player()

    result = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))

        result.append({
            "name": p["name"],
            "tag": tag,
            "role": p.get("role"),
            "score": p.get("score", 0),
            "fame_per_deck": p.get("fame_per_deck", 0),
            "trophies": p.get("trophies", 0),
            "donations": p.get("donations", 0),
            "strikes": p.get("strikes", 0),
            "participation_count": p.get("participation_count", 0),
            "focus_badge": focus["badge"],
            "trend": compute_trend(scores) if scores else "",
            "streak": compute_streak(scores),
        })

    result.sort(key=lambda x: (-x["score"], -x["fame_per_deck"], -x["trophies"]))
    for i, entry in enumerate(result):
        entry["rank"] = i + 1

    return {"players": result, "total": len(result)}


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 6: ECHTZEIT-KRIEG (LIVE CR-API)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/war/mahnwache")
def war_mahnwache():
    """Wer hat heute noch offene Decks? (Benötigt CR_API_KEY auf Render)"""
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/currentriverrace")
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    clan = data.get("clan", {})
    participants = clan.get("participants", [])
    state = data.get("state", "unknown")

    if state not in ("warDay", "war"):
        return {
            "state": state,
            "message": "Aktuell kein aktiver Kriegstag – keine offenen Decks.",
            "open_decks": [],
        }

    open_decks = []
    for p in participants:
        open_today = p.get("decksOpenToday", 0)
        if open_today > 0:
            open_decks.append({
                "name": p.get("name"),
                "tag": p.get("tag"),
                "decks_open_today": open_today,
                "decks_used_today": p.get("decksUsedToday", 0),
                "fame": p.get("fame", 0),
                "boat_attacks": p.get("boatAttacks", 0),
            })

    open_decks.sort(key=lambda x: -x["decks_open_today"])

    return {
        "state": state,
        "open_decks_count": len(open_decks),
        "open_decks": open_decks,
        "message": f"{len(open_decks)} Spieler haben noch offene Decks heute!" if open_decks else "Alle Decks heute gespielt! 🎉",
    }


@app.get("/war/radar")
def war_radar():
    """Live-Standings aller Clans im aktuellen River Race. (Benötigt CR_API_KEY)"""
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/currentriverrace")
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    clans_data = data.get("clans", [])
    state = data.get("state", "unknown")

    standings = []
    for clan in clans_data:
        standings.append({
            "name": clan.get("name"),
            "tag": clan.get("tag"),
            "fame": clan.get("fame", 0),
            "repair_points": clan.get("repairPoints", 0),
        })

    standings.sort(key=lambda x: -x["fame"])
    for i, s in enumerate(standings):
        s["rank"] = i + 1

    our_entry = next((s for s in standings if s["tag"] == CLAN_TAG_RAW), None)
    our_rank = our_entry["rank"] if our_entry else None
    leader_fame = standings[0]["fame"] if standings else 0
    fame_gap = (leader_fame - our_entry["fame"]) if our_entry and our_rank and our_rank > 1 else 0

    return {
        "state": state,
        "our_rank": our_rank,
        "our_fame": our_entry["fame"] if our_entry else 0,
        "fame_gap_to_leader": fame_gap,
        "standings": standings,
    }


@app.get("/war/prognose")
def war_prognose():
    """Fame-Prognose: Können wir den Krieg noch gewinnen? (Benötigt CR_API_KEY)"""
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/currentriverrace")
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    clan = data.get("clan", {})
    clans_data = data.get("clans", [])
    state = data.get("state", "unknown")
    participants = clan.get("participants", [])

    our_fame = clan.get("fame", 0)
    decks_used_today = sum(p.get("decksUsedToday", 0) for p in participants)
    remaining_decks = sum(p.get("decksOpenToday", 0) for p in participants)
    avg_fame_per_deck = round(our_fame / decks_used_today) if decks_used_today > 0 else 150

    projected_fame = our_fame + round(remaining_decks * avg_fame_per_deck)

    standings = sorted(clans_data, key=lambda c: -c.get("fame", 0))
    our_rank = next((i + 1 for i, c in enumerate(standings) if c.get("tag") == CLAN_TAG_RAW), None)
    leader_fame = standings[0].get("fame", 0) if standings else 0
    second_fame = standings[1].get("fame", 0) if len(standings) > 1 else 0

    can_win = projected_fame > leader_fame
    can_reach_top2 = projected_fame > second_fame if our_rank and our_rank > 2 else True

    return {
        "state": state,
        "current_fame": our_fame,
        "remaining_decks": remaining_decks,
        "avg_fame_per_deck": avg_fame_per_deck,
        "projected_fame": projected_fame,
        "current_rank": our_rank,
        "leader_fame": leader_fame,
        "prognose": (
            "🏆 Sieg möglich!" if can_win else
            "🥈 Top 2 erreichbar" if can_reach_top2 else
            "⚔️ Schwierig – alle Decks müssen gespielt werden"
        ),
        "message": f"Mit {remaining_decks} offenen Decks und ~{avg_fame_per_deck} Fame/Deck → projiziertes Fame: {projected_fame}",
    }


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 7: TRENDS & STREAKS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/players/trends")
def players_trends():
    """Score-Trends und Deltas aller Spieler der letzten 6 Wochen."""
    all_players = build_players_enriched()
    history = score_history_by_player()

    result = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        trend = compute_trend(scores) if scores else "–"
        streak = compute_streak(scores)
        delta = round(scores[-1] - scores[-2], 2) if len(scores) >= 2 else None

        result.append({
            "name": p["name"],
            "tag": tag,
            "score": p.get("score", 0),
            "trend": trend,
            "streak": streak,
            "streak_badge": f"🔥 {streak}" if streak >= 3 else None,
            "delta": delta,
            "delta_symbol": "📈" if delta is not None and delta > 5 else "📉" if delta is not None and delta < -5 else "➡️" if delta is not None else "–",
        })

    result.sort(key=lambda x: -x["score"])
    return {"players": result, "total": len(result)}


@app.get("/players/streaks")
def players_streaks():
    """Spieler mit aktivem Streak (2+ perfekte Wochen in Folge mit 100% Score)."""
    all_players = build_players_enriched()
    history = score_history_by_player()

    result = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        streak = compute_streak(scores)
        if streak >= 2:
            result.append({
                "name": p["name"],
                "tag": tag,
                "streak": streak,
                "badge": f"🔥 {streak}x 100%",
                "score": p.get("score", 0),
            })

    result.sort(key=lambda x: -x["streak"])
    return {
        "players": result,
        "message": f"{len(result)} Spieler mit aktivem Streak" if result else "Aktuell keine aktiven Streaks",
    }


@app.get("/players/comebacks")
def players_comebacks():
    """Größte Score-Verbesserungen gegenüber der vorherigen Woche."""
    all_players = build_players_enriched()
    history = score_history_by_player()
    clan_records = load_records()

    result = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        if len(scores) >= 2:
            delta = round(scores[-1] - scores[-2], 2)
            if delta > 0:
                result.append({
                    "name": p["name"],
                    "tag": tag,
                    "previous_score": scores[-2],
                    "current_score": scores[-1],
                    "improvement": delta,
                    "badge": "🚀 Mega-Comeback!" if delta >= 30 else "📈 Verbesserung",
                })

    result.sort(key=lambda x: -x["improvement"])
    record_delta = clan_records.get("delta", {}) if isinstance(clan_records, dict) else {}

    return {
        "comebacks": result[:10],
        "all_time_record": {
            "name": record_delta.get("name"),
            "improvement": record_delta.get("val"),
        } if record_delta else None,
    }


@app.get("/player/{player_tag}/streak")
def player_streak(player_tag: str):
    """Aktueller Streak und Score-Trend eines einzelnen Spielers."""
    tag = normalize_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    history = score_history_by_player()
    entries = history.get(normalize_name(p["name"]), [])
    scores = [e["score"] for e in entries]
    streak = compute_streak(scores)
    trend = compute_trend(scores) if scores else ""

    return {
        "name": p["name"],
        "tag": tag,
        "streak": streak,
        "streak_badge": f"🔥 {streak}x perfekt" if streak >= 3 else (f"🔥 {streak}" if streak >= 2 else "Kein aktiver Streak"),
        "trend": trend,
        "recent_scores": scores[-6:],
        "current_score": p.get("score", 0),
    }


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 9: BEFÖRDERUNGSFORTSCHRITT
# ════════════════════════════════════════════════════════════════════════════

@app.get("/promotions/progress")
def promotions_progress():
    """Beförderungsfortschritt aller Members – sortiert nach Gesamtfortschritt."""
    all_players = list(build_players_enriched().values())

    result = []
    for p in all_players:
        role = normalize_name(p.get("role", "member"))
        if role in {"member", "mitglied", ""}:
            status = build_promotion_status(p)
            result.append({"name": p["name"], "tag": p.get("tag"), **status})

    result.sort(key=lambda x: -x["overall_progress_pct"])
    return {
        "candidates": result,
        "ready_count": sum(1 for r in result if r["eligible"]),
        "total_members": len(result),
    }


@app.get("/player/{player_tag}/promotion-status")
def player_promotion_status(player_tag: str):
    """Detaillierter Beförderungsstatus eines Spielers: was fehlt noch?"""
    tag = normalize_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    status = build_promotion_status(p)
    return {"name": p["name"], "tag": tag, **status}


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 11: COACH-ECKE
# ════════════════════════════════════════════════════════════════════════════

@app.get("/coaching/tips")
def coaching_tips():
    """Aktuelle Coaching-Hinweise für den Clan-Leader basierend auf den Daten."""
    all_players = list(build_players_enriched().values())
    tips = []

    # Schwache Leistung
    low_performers = [p for p in all_players if p.get("score", 0) < APP_CONFIG["STRIKE_THRESHOLD"]]
    if low_performers:
        names = ", ".join(p["name"] for p in low_performers[:5])
        tips.append({
            "category": "⚠️ Leistung",
            "priority": "hoch",
            "tip": f"{len(low_performers)} Spieler unter {APP_CONFIG['STRIKE_THRESHOLD']}% Score: {names}",
            "action": "Strike-Gespräch führen oder Warnung aussprechen",
        })

    # Strike-Alarm
    high_strikes = [p for p in all_players if p.get("strikes", 0) >= 3]
    if high_strikes:
        names = ", ".join(p["name"] for p in high_strikes)
        tips.append({
            "category": "🚨 Strike-Alarm",
            "priority": "hoch",
            "tip": f"{len(high_strikes)} Spieler mit ≥3 Strikes: {names}",
            "action": "Letzte Warnung oder Kick erwägen",
        })

    # Deck-Qualität
    fame_values = [p.get("fame_per_deck", 0) for p in all_players if p.get("fame_per_deck", 0) > 0]
    avg_fame = sum(fame_values) / len(fame_values) if fame_values else 0
    if avg_fame < APP_CONFIG["BADGE_STABIL_FAME"]:
        tips.append({
            "category": "🎯 Deck-Qualität",
            "priority": "mittel",
            "tip": f"Clan-Durchschnitt: {round(avg_fame, 1)} Fame/Deck (Ziel: ≥{APP_CONFIG['BADGE_STABIL_FAME']})",
            "action": "Deck-Optimierung empfehlen – Top-Decks im Clan-Chat teilen",
        })

    # Teamplay
    teamplay = calculate_teamplay_score_from_stats(all_players)
    if teamplay["score"] < 35:
        tips.append({
            "category": "🤝 Teamplay",
            "priority": "mittel",
            "tip": f"Teamplay-Score: {teamplay['score']} – {teamplay['leecher']} Schmarotzer, {teamplay['sleeper']} Schläfer",
            "action": "Spendenkultur ansprechen – Erinnerung im Chat posten",
        })

    # Beförderungskandidaten
    promo_candidates = build_promotion_candidates()
    if promo_candidates:
        names = ", ".join(p["name"] for p in promo_candidates[:3])
        tips.append({
            "category": "🎖️ Beförderungen",
            "priority": "niedrig",
            "tip": f"{len(promo_candidates)} Spieler bereit für Elder-Beförderung: {names}",
            "action": "Beförderung durchführen und öffentlich beglückwünschen",
        })

    if not tips:
        tips.append({
            "category": "✅ Alles gut",
            "priority": "info",
            "tip": "Clan läuft gut – keine kritischen Punkte erkennbar",
            "action": "Weiter so! Positive Leistungen öffentlich loben",
        })

    return {
        "tips": tips,
        "total": len(tips),
        "high_priority": sum(1 for t in tips if t["priority"] == "hoch"),
    }


@app.get("/coaching/messages")
def coaching_messages():
    """Vorgefertigte Nachrichten-Templates für häufige Clan-Situationen."""
    return {
        "hinweis": "Ersetze {name}, {score}, {strikes} mit echten Werten aus /player/{tag} oder /warnings",
        "categories": {
            "willkommen": {
                "title": "Willkommensnachricht",
                "templates": [
                    "Willkommen im Clan, {name}! 🎉 Schön, dass du dabei bist. Lies dir die Clan-Regeln durch und meld dich bei Fragen!",
                    "Hey {name}, herzlich willkommen bei HAMBURG! 🏆 Viel Spaß beim Spielen – wir freuen uns auf dich!",
                ],
            },
            "krieg_erinnerung": {
                "title": "Kriegs-Erinnerung",
                "templates": [
                    "⚔️ Kriegstag läuft! Bitte alle Decks nutzen – auch 1 Deck zählt! Gemeinsam schaffen wir das! 💪",
                    "Noch offene Decks da? Jetzt ist die Zeit! Jedes Deck zählt für den Clan. Los geht's! 🔥",
                    "Kriegstag Reminder: Alle Decks spielen, egal mit welchem Score. Dabei sein ist alles! ⚔️",
                ],
            },
            "warnung": {
                "title": "Warnung / Strike",
                "templates": [
                    "{name}, dein Score liegt bei {score}% – das ist unter unserer Mindestgrenze von 50%. Das ist Strike {strikes}. Bitte beim nächsten Krieg mehr Decks nutzen.",
                    "Hey {name}, kurze Rückmeldung: {score}% ist nicht ausreichend. Wir erwarten mindestens 50%. Beim nächsten Krieg bitte vollen Einsatz! 🙏",
                ],
            },
            "befoerderung": {
                "title": "Beförderung zu Elder",
                "templates": [
                    "🎖️ Herzlichen Glückwunsch, {name}! Du wirst heute zum Elder befördert. Dein Einsatz hat das verdient. Weiter so! 🏆",
                    "Großes Lob an {name}! 🌟 Für deinen konstanten Einsatz wirst du zum Elder befördert. Danke für alles!",
                ],
            },
            "lob": {
                "title": "Lob / Anerkennung",
                "templates": [
                    "Riesenlob an {name} für {score}% Score diese Woche! 🔥 So macht Clan-Krieg Spaß!",
                    "Top-Performance von {name} mit {score}%! ⭐ Du bist ein echter Leistungsträger!",
                    "Shoutout an {name} – perfekte Woche mit 100%! 🏆🔥 Respekt!",
                ],
            },
            "kick": {
                "title": "Kick-Nachricht",
                "templates": [
                    "{name}, leider müssen wir dich aufgrund anhaltend niedriger Leistungen entfernen. Du kannst dich gerne wieder bewerben, wenn du aktiver spielen kannst.",
                    "Hey {name}, wir haben dich leider aus dem Clan entfernt. Du bist jederzeit herzlich willkommen zurückzukehren, wenn die Zeit passt!",
                ],
            },
        },
    }


@app.get("/player/{player_tag}/coaching")
def player_coaching(player_tag: str):
    """Individueller Coaching-Hinweis und vorgeschlagene Nachricht für einen Spieler."""
    tag = normalize_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    score = p.get("score", 0)
    fame = p.get("fame_per_deck", 0)
    strikes = p.get("strikes", 0)
    donations = p.get("donations", 0)
    received = p.get("donations_received", 0)
    participation = p.get("participation_count", 0)

    tips = []
    messages = []

    if participation <= APP_CONFIG["MIN_PARTICIPATION"]:
        tips.append("🌱 Noch im Welpenschutz – einfach mitspielen, noch keine Bewertung!")
    elif score < APP_CONFIG["STRIKE_THRESHOLD"]:
        tips.append(f"⚠️ Score {score}% unter Grenze ({APP_CONFIG['STRIKE_THRESHOLD']}%) – mehr Kriege aktiv mitspielen")
        if strikes > 0:
            tips.append(f"🚨 {strikes} Strike(s) vorhanden – dringend verbessern")
        messages.append(
            f"Hey {p['name']}, dein Score liegt bei {score}%. Bitte beim nächsten Krieg alle Decks nutzen. "
            f"Das wäre Strike {strikes + 1}, wenn es so weitergeht."
        )
    elif score >= APP_CONFIG["BADGE_STARK_SCORE"] and fame >= APP_CONFIG["BADGE_STARK_FAME"]:
        tips.append(f"⭐ Top-Performer! Score {score}%, {fame} Fame/Deck – weiter so!")
        messages.append(f"Riesenlob an {p['name']}! {score}% Score und starke Deck-Qualität – echter Leistungsträger! 🏆")
    elif fame < APP_CONFIG["DROPPER_THRESHOLD"]:
        tips.append(f"🎯 Fame/Deck ({fame}) ausbaufähig – stärkere Decks nutzen (Ziel: ≥{APP_CONFIG['DROPPER_THRESHOLD']})")
        messages.append(f"Hey {p['name']}, du bist dabei – super! Probiere mal stärkere Decks für mehr Punkte. 💪")
    else:
        tips.append(f"🛡️ Solide Leistung mit {score}% Score – weiter so!")

    if donations == 0 and received > 0:
        tips.append(f"📦 {received} Karten erhalten, aber nichts gespendet – bitte auch spenden!")
        messages.append(f"Hey {p['name']}, denk bitte ans Spenden! Du hast {received} Karten bekommen, aber noch nichts zurückgegeben. 🙏")

    focus = get_focus_badge(score, fame, participation)

    return {
        "name": p["name"],
        "tag": tag,
        "score": score,
        "fame_per_deck": fame,
        "strikes": strikes,
        "focus": focus,
        "coaching_tips": tips,
        "suggested_messages": messages,
    }


# ════════════════════════════════════════════════════════════════════════════
# GRUPPE 12: SPIELER-VERGLEICH
# ════════════════════════════════════════════════════════════════════════════

@app.get("/compare")
def compare(
    tags: str = Query(..., description="Kommagetrennte Spieler-Tags, z.B. %23TAG1,%23TAG2 (max. 4 Spieler)")
):
    """Vergleicht bis zu 4 Spieler direkt miteinander."""
    tag_list = [normalize_tag(t.strip()) for t in tags.split(",")]
    if len(tag_list) < 2:
        raise HTTPException(status_code=400, detail="Mindestens 2 Tags angeben (kommagetrennt)")

    all_players = build_players_enriched()
    history = score_history_by_player()

    comparison = []
    for tag in tag_list[:4]:
        if tag not in all_players:
            comparison.append({"tag": tag, "error": "Spieler nicht gefunden"})
            continue

        p = all_players[tag]
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))
        promo_status = build_promotion_status(p)

        comparison.append({
            "name": p["name"],
            "tag": tag,
            "role": p.get("role"),
            "score": p.get("score", 0),
            "fame_per_deck": p.get("fame_per_deck", 0),
            "trophies": p.get("trophies", 0),
            "donations": p.get("donations", 0),
            "donations_received": p.get("donations_received", 0),
            "strikes": p.get("strikes", 0),
            "participation_count": p.get("participation_count", 0),
            "focus": focus,
            "trend": compute_trend(scores) if scores else "",
            "streak": compute_streak(scores),
            "promotion_progress_pct": promo_status["overall_progress_pct"],
            "promotion_ready": promo_status["eligible"],
        })

    valid = [c for c in comparison if "error" not in c]
    verdict = None
    if len(valid) >= 2:
        verdict = {
            "best_score": max(valid, key=lambda x: x["score"])["name"],
            "best_fame_per_deck": max(valid, key=lambda x: x["fame_per_deck"])["name"],
            "most_trophies": max(valid, key=lambda x: x["trophies"])["name"],
            "top_donor": max(valid, key=lambda x: x["donations"])["name"],
            "promotion_leader": max(valid, key=lambda x: x["promotion_progress_pct"])["name"],
        }

    return {"players": comparison, "verdict": verdict}


# ════════════════════════════════════════════════════════════════════════════
# ZUSAMMENGEFÜHRTE ENDPUNKTE (Schema-Slot-optimiert)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/war/status")
def war_status():
    """Alles zum aktuellen Krieg in einem Aufruf: offene Decks, Standings, Prognose. (Benötigt CR_API_KEY)"""
    data = fetch_currentriverrace()
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    state = data.get("state", "unknown")
    clan = data.get("clan", {})
    clans_data = data.get("clans", [])
    participants = clan.get("participants", [])

    # Offene Decks (Mahnwache)
    open_decks = []
    if state in ("warDay", "war"):
        for p in participants:
            if p.get("decksOpenToday", 0) > 0:
                open_decks.append({
                    "name": p.get("name"),
                    "tag": p.get("tag"),
                    "decks_open_today": p.get("decksOpenToday", 0),
                    "decks_used_today": p.get("decksUsedToday", 0),
                    "fame": p.get("fame", 0),
                    "boat_attacks": p.get("boatAttacks", 0),
                })
        open_decks.sort(key=lambda x: -x["decks_open_today"])

    # Standings (Radar)
    standings = []
    for c in clans_data:
        standings.append({
            "name": c.get("name"),
            "tag": c.get("tag"),
            "fame": c.get("fame", 0),
            "repair_points": c.get("repairPoints", 0),
        })
    standings.sort(key=lambda x: -x["fame"])
    for i, s in enumerate(standings):
        s["rank"] = i + 1

    our_entry = next((s for s in standings if s["tag"] == CLAN_TAG_RAW), None)
    our_rank = our_entry["rank"] if our_entry else None
    our_fame = our_entry["fame"] if our_entry else clan.get("fame", 0)
    leader_fame = standings[0]["fame"] if standings else 0

    # Prognose
    decks_used_today = sum(p.get("decksUsedToday", 0) for p in participants)
    remaining_decks = sum(p.get("decksOpenToday", 0) for p in participants)
    avg_fame_per_deck = round(our_fame / decks_used_today) if decks_used_today > 0 else 150
    projected_fame = our_fame + round(remaining_decks * avg_fame_per_deck)
    second_fame = standings[1]["fame"] if len(standings) > 1 else 0
    can_win = projected_fame > leader_fame
    can_top2 = projected_fame > second_fame if our_rank and our_rank > 2 else True

    return {
        "state": state,
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "cache_hinweis": "⚠️ CR-API cached Daten für 2–5 Minuten. Bei Abweichungen zum Spiel: Ingame-Stand hat immer Vorrang.",
        "mahnwache": {
            "open_decks_count": len(open_decks),
            "open_decks": open_decks,
            "message": f"{len(open_decks)} Spieler haben noch offene Decks!" if open_decks else "Alle Decks gespielt! 🎉",
        },
        "radar": {
            "our_rank": our_rank,
            "our_fame": our_fame,
            "fame_gap_to_leader": max(0, leader_fame - our_fame),
            "standings": standings,
        },
        "prognose": {
            "remaining_decks": remaining_decks,
            "avg_fame_per_deck": avg_fame_per_deck,
            "projected_fame": projected_fame,
            "verdict": (
                "🏆 Sieg möglich!" if can_win else
                "🥈 Top 2 erreichbar" if can_top2 else
                "⚔️ Schwierig – alle Decks müssen gespielt werden"
            ),
        },
    }


@app.get("/player/{player_tag}/stats")
def player_stats_combined(player_tag: str):
    """Kompakt-Statistik eines Spielers: Focus-Badge, Streak, Trend, Welpenschutz in einem Aufruf."""
    tag = normalize_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    history = score_history_by_player()
    entries = history.get(normalize_name(p["name"]), [])
    scores = [e["score"] for e in entries]

    focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))
    streak = compute_streak(scores)
    trend = compute_trend(scores) if scores else ""
    is_welpenschutz = p.get("participation_count", 0) <= APP_CONFIG["MIN_PARTICIPATION"]

    return {
        "name": p["name"],
        "tag": tag,
        "role": p.get("role"),
        "score": p.get("score", 0),
        "fame_per_deck": p.get("fame_per_deck", 0),
        "trophies": p.get("trophies", 0),
        "participation_count": p.get("participation_count", 0),
        "focus": focus,
        "welpenschutz": is_welpenschutz,
        "wars_until_evaluated": max(0, APP_CONFIG["MIN_PARTICIPATION"] + 1 - p.get("participation_count", 0)) if is_welpenschutz else 0,
        "trend": trend,
        "streak": streak,
        "streak_badge": f"🔥 {streak}x perfekt" if streak >= 3 else (f"🔥 {streak}" if streak >= 2 else None),
        "recent_scores": scores[-6:],
        "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "best_score": max(scores) if scores else 0,
    }


@app.get("/players/meta")
def players_meta():
    """Trends, Streaks und Comebacks aller Spieler in einem Aufruf."""
    all_players = build_players_enriched()
    history = score_history_by_player()
    clan_records = load_records()

    trends = []
    streaks = []
    comebacks = []

    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        trend = compute_trend(scores) if scores else "–"
        streak = compute_streak(scores)
        delta = round(scores[-1] - scores[-2], 2) if len(scores) >= 2 else None

        trends.append({
            "name": p["name"],
            "tag": tag,
            "score": p.get("score", 0),
            "trend": trend,
            "streak": streak,
            "streak_badge": f"🔥 {streak}" if streak >= 3 else None,
            "delta": delta,
            "delta_symbol": "📈" if delta is not None and delta > 5 else "📉" if delta is not None and delta < -5 else "➡️" if delta is not None else "–",
        })

        if streak >= 2:
            streaks.append({
                "name": p["name"],
                "tag": tag,
                "streak": streak,
                "badge": f"🔥 {streak}x 100%",
                "score": p.get("score", 0),
            })

        if len(scores) >= 2:
            improvement = round(scores[-1] - scores[-2], 2)
            if improvement > 0:
                comebacks.append({
                    "name": p["name"],
                    "tag": tag,
                    "previous_score": scores[-2],
                    "current_score": scores[-1],
                    "improvement": improvement,
                    "badge": "🚀 Mega-Comeback!" if improvement >= 30 else "📈 Verbesserung",
                })

    trends.sort(key=lambda x: -x["score"])
    streaks.sort(key=lambda x: -x["streak"])
    comebacks.sort(key=lambda x: -x["improvement"])
    record_delta = clan_records.get("delta", {}) if isinstance(clan_records, dict) else {}

    return {
        "trends": trends,
        "streaks": {
            "players": streaks,
            "message": f"{len(streaks)} Spieler mit aktivem Streak" if streaks else "Aktuell keine aktiven Streaks",
        },
        "comebacks": {
            "top10": comebacks[:10],
            "all_time_record": {"name": record_delta.get("name"), "improvement": record_delta.get("val")} if record_delta else None,
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# NEUE LIVE-ENDPUNKTE (CR_API_KEY)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/war/history")
def war_history():
    """Vollständiger River-Race-Verlauf: Rang, Fame, Trophäen-Änderung pro vergangenen Krieg. (Benötigt CR_API_KEY)"""
    items = fetch_riverracelog()
    if items is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    history = []
    for item in items:
        standings = item.get("standings", [])
        our_standing = next(
            (s for s in standings if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
        )
        our_rank = next(
            (i + 1 for i, s in enumerate(standings) if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
        )
        clan = our_standing.get("clan", {}) if our_standing else {}
        participants = clan.get("participants", [])
        total_fame = clan.get("fame", 0)
        total_decks = sum(p.get("decksUsed", 0) for p in participants)

        history.append({
            "season_id": item.get("seasonId"),
            "section_index": item.get("sectionIndex"),
            "created_date": item.get("createdDate"),
            "our_rank": our_rank,
            "total_clans": len(standings),
            "our_fame": total_fame,
            "trophy_change": our_standing.get("trophyChange", 0) if our_standing else 0,
            "participants_count": len(participants),
            "total_decks_used": total_decks,
            "avg_fame_per_deck": round(total_fame / total_decks) if total_decks > 0 else 0,
            "top_scorer": max(participants, key=lambda x: x.get("fame", 0)).get("name") if participants else None,
        })

    wins = sum(1 for h in history if h["our_rank"] == 1)
    top2 = sum(1 for h in history if h["our_rank"] and h["our_rank"] <= 2)

    return {
        "races": history,
        "total_races": len(history),
        "wins": wins,
        "top2_finishes": top2,
        "avg_rank": round(sum(h["our_rank"] for h in history if h["our_rank"]) / len([h for h in history if h["our_rank"]]), 1) if history else None,
    }


@app.get("/war/live-participants")
def war_live_participants():
    """Vollständige Live-Liste aller aktuellen Kriegsteilnehmer mit Fame, Decks und Boat Attacks. (Benötigt CR_API_KEY)"""
    data = fetch_currentriverrace()
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    state = data.get("state", "unknown")
    clan = data.get("clan", {})
    participants = clan.get("participants", [])

    result = []
    for p in participants:
        decks_used = p.get("decksUsed", 0)
        fame = p.get("fame", 0)
        result.append({
            "name": p.get("name"),
            "tag": p.get("tag"),
            "fame": fame,
            "decks_used": decks_used,
            "decks_used_today": p.get("decksUsedToday", 0),
            "decks_open_today": p.get("decksOpenToday", 0),
            "boat_attacks": p.get("boatAttacks", 0),
            "repair_points": p.get("repairPoints", 0),
            "avg_fame_per_deck": round(fame / decks_used) if decks_used > 0 else 0,
        })

    result.sort(key=lambda x: -x["fame"])
    total_fame = sum(p["fame"] for p in result)
    total_decks = sum(p["decks_used"] for p in result)

    return {
        "state": state,
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "cache_hinweis": "⚠️ CR-API cached Daten für 2–5 Minuten. Bei Abweichungen zum Spiel: Ingame-Stand hat immer Vorrang.",
        "participants": result,
        "total_participants": len(result),
        "clan_fame": total_fame,
        "clan_decks_used": total_decks,
        "clan_avg_fame_per_deck": round(total_fame / total_decks) if total_decks > 0 else 0,
    }


@app.get("/player/{player_tag}/battlelog")
def player_battlelog(player_tag: str):
    """Letzte River-Race-Kämpfe eines Spielers live: Ergebnis, Kronen, eigenes Deck, Gegner-Deck. (Benötigt CR_API_KEY)"""
    tag = normalize_tag(player_tag)
    tag_encoded = f"%23{tag.lstrip('#')}"
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    data = cr_api_get(f"/players/{tag_encoded}/battlelog")
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    battles = data if isinstance(data, list) else []
    river_race_battles = [b for b in battles if "riverRace" in b.get("type", "").lower() or "river" in b.get("type", "").lower()][:25]

    result = []
    for b in river_race_battles:
        team = b.get("team", [{}])[0] if b.get("team") else {}
        opponent = b.get("opponent", [{}])[0] if b.get("opponent") else {}
        player_crowns = team.get("crowns", 0)
        opp_crowns = opponent.get("crowns", 0)

        result.append({
            "battle_time": b.get("battleTime"),
            "type": b.get("type"),
            "result": "win" if player_crowns > opp_crowns else "loss" if player_crowns < opp_crowns else "draw",
            "crowns": player_crowns,
            "opponent_crowns": opp_crowns,
            "opponent_name": opponent.get("name"),
            "opponent_tag": opponent.get("tag"),
            "player_deck": [c.get("name") for c in team.get("cards", []) if isinstance(c, dict)],
            "opponent_deck": [c.get("name") for c in opponent.get("cards", []) if isinstance(c, dict)],
        })

    wins = sum(1 for b in result if b["result"] == "win")
    total = len(result)

    return {
        "tag": tag,
        "name": all_players[tag]["name"],
        "battles": result,
        "total_battles": total,
        "wins": wins,
        "losses": total - wins,
        "winrate_pct": round(wins / total * 100, 1) if total > 0 else 0,
    }


@app.get("/player/{player_tag}/live")
def player_live(player_tag: str):
    """Live-Profil eines Spielers direkt aus der CR-API: aktuelle Trophäen, Rolle, Donationen. (Benötigt CR_API_KEY)"""
    tag = normalize_tag(player_tag)
    tag_encoded = f"%23{tag.lstrip('#')}"

    data = cr_api_get(f"/players/{tag_encoded}")
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    clan_info = data.get("clan", {})
    return {
        "name": data.get("name"),
        "tag": data.get("tag"),
        "trophies": data.get("trophies"),
        "best_trophies": data.get("bestTrophies"),
        "level": data.get("expLevel"),
        "war_day_wins": data.get("warDayWins"),
        "donations": data.get("donations"),
        "donations_received": data.get("donationsReceived"),
        "donations_total": data.get("totalDonations"),
        "clan_name": clan_info.get("name"),
        "clan_tag": clan_info.get("tag"),
        "role": data.get("role"),
        "last_seen": data.get("lastSeen"),
        "arena": data.get("arena", {}).get("name"),
    }


@app.get("/clan/live")
def clan_live():
    """Live Clan-Profil: Mitglieder, Trophäen, Liga, Spenden-Woche. (Benötigt CR_API_KEY)"""
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}")
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="CR-API nicht verfügbar. Bitte CR_API_KEY als Umgebungsvariable auf Render setzen.",
        )

    member_list = data.get("memberList", [])
    members_summary = [
        {
            "name": m.get("name"),
            "tag": m.get("tag"),
            "role": m.get("role"),
            "trophies": m.get("trophies"),
            "donations": m.get("donations"),
            "donations_received": m.get("donationsReceived"),
        }
        for m in member_list
    ]
    members_summary.sort(key=lambda x: -x["trophies"])

    return {
        "name": data.get("name"),
        "tag": data.get("tag"),
        "description": data.get("description"),
        "type": data.get("type"),
        "members": data.get("members"),
        "required_trophies": data.get("requiredTrophies"),
        "clan_score": data.get("clanScore"),
        "clan_war_trophies": data.get("clanWarTrophies"),
        "donations_per_week": data.get("donationsPerWeek"),
        "location": data.get("location", {}).get("name"),
        "member_list": members_summary,
    }
